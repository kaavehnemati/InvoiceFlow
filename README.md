# InvoiceFlow

A backend platform for ingesting, validating, processing, and tracking invoices.

**Current status:** Phase 9 — service layer. The three layers are in place: routes handle
HTTP, `InvoiceService` owns the business rules, `InvoiceRepository` owns persistence. Routes
still wire their own collaborators by hand, and errors are still raised as
`HTTPException` from the router. Each is addressed by a later
phase of [the implementation playbook](InvoiceFlow_Claude_Code_Implementation_Playbook.md),
and only once the previous phase makes the need for it obvious.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for environment and dependency management
- PostgreSQL 16

> The system Python on this machine ships without `pip` and without `ensurepip`, so
> `python3 -m venv` cannot bootstrap itself. `uv` handles both the virtual environment and
> the installs without needing `sudo`.

## Database

The application needs a PostgreSQL database before it will start.

```bash
sudo service postgresql start
sudo -u postgres psql -c "CREATE ROLE invoiceflow LOGIN PASSWORD 'invoiceflow';"
sudo -u postgres createdb -O invoiceflow invoiceflow
```

Confirm it is reachable — this should print `1`:

```bash
psql "postgresql://invoiceflow:invoiceflow@localhost:5432/invoiceflow" -c "select 1"
```

### Connection

The connection string is read from the `DATABASE_URL` environment variable. If it is unset,
the application falls back to the local development default:

```text
postgresql+psycopg://invoiceflow:invoiceflow@localhost:5432/invoiceflow
```

The `+psycopg` suffix selects the psycopg 3 driver. To point at a different database:

```bash
DATABASE_URL="postgresql+psycopg://user:pass@host:5432/dbname" uv run uvicorn app.main:app
```

`invoiceflow/invoiceflow` is a local development credential, not a secret, and no real
credential belongs in source. Phase 11 replaces this single `os.getenv` call with a settings
object and a `.env.example`.

### Migrations

The schema is managed by [Alembic](https://alembic.sqlalchemy.org/). The application does
not create tables — starting it against an empty database gives you an empty database. Build
the schema explicitly:

```bash
uv run alembic upgrade head
```

| Command | Does |
| --- | --- |
| `alembic upgrade head` | Apply every migration not yet applied |
| `alembic current` | Which revision this database is on |
| `alembic history` | The full revision chain |
| `alembic downgrade -1` | Undo the most recent migration |
| `alembic downgrade base` | Undo everything |
| `alembic revision --autogenerate -m "..."` | Draft a migration from model changes |

Migrations live in `migrations/versions/`. The connection string comes from `DATABASE_URL`
via [migrations/env.py](migrations/env.py) — the `sqlalchemy.url` placeholder in
`alembic.ini` is never used, so no credential is committed.

> **Read what `--autogenerate` produces before applying it.** It diffs two schemas and knows
> nothing about the rows in between. Adding a `NOT NULL` column, renaming anything, or
> changing a type will generate a statement that is correct against an empty table and wrong
> against a populated one. [The `updated_at`
> migration](migrations/versions/) is a worked example: the generated one-liner fails, and
> the committed version adds the column nullable, backfills it, then applies the constraint.

### Resetting during development

Alembic ships no `migrate:fresh` equivalent, so pick the one that matches what you actually
want. **None of these belong anywhere near production.**

```bash
# clear the data, keep the schema  — fastest, and usually the one you want
psql "$DATABASE_URL" -c "TRUNCATE invoices RESTART IDENTITY CASCADE"

# rebuild the schema from nothing  — most reliable
psql "$DATABASE_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
uv run alembic upgrade head

# rebuild by replaying the rollbacks — also tests that downgrades work
uv run alembic downgrade base && uv run alembic upgrade head
```

The last two are not equivalent. `downgrade base` *executes your `downgrade()` functions*, so
it fails partway if any migration is not truly reversible — which makes it a useful test, but
an unreliable reset. Dropping the schema ignores the migration files entirely.

Never truncate `alembic_version`: that makes Alembic believe nothing was ever applied while
the tables are still there. If you need Alembic's record to match a schema that already
exists, `alembic stamp head` sets the pointer without running any DDL.

## Setup

```bash
uv venv
uv pip install -r requirements.txt
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

`app.main:app` means: import the module `app.main`, then serve the object named `app` inside
it. `--reload` restarts the server whenever a source file changes, which is convenient in
development and should never be used in production.

## Verify

With the server running:

| URL | Expected |
| --- | --- |
| <http://127.0.0.1:8000/> | `{"message":"InvoiceFlow API"}` |
| <http://127.0.0.1:8000/docs> | Interactive Swagger UI |
| <http://127.0.0.1:8000/openapi.json> | The generated OpenAPI schema |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Service banner |
| `POST` | `/invoices` | Create an invoice |
| `GET` | `/invoices` | List all invoices |
| `GET` | `/invoices/{invoice_id}` | Fetch one invoice by ID |

### Examples

### Schemas

The request and response contracts are declared separately, and both appear in `/docs`.

**`InvoiceCreate`** — what a client sends. All seven fields are required; anything missing or
of the wrong type is rejected with `422` before the handler runs.

| Field | Type |
| --- | --- |
| `invoice_number` | string |
| `vendor` | string |
| `invoice_date` | date, `YYYY-MM-DD` |
| `currency` | string |
| `subtotal`, `tax`, `total` | decimal |

**`InvoiceRead`** — what the API returns: the same seven fields plus three the server assigns
and a client can never supply.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | integer | Assigned on create |
| `status` | string | `VALID` — an invoice is only stored if it passes every business rule |
| `created_at` | datetime | UTC |
| `updated_at` | datetime | UTC; equals `created_at` until something modifies the invoice |

## Business rules

Passing the schema means an invoice has the right *shape*. These rules decide whether it
makes *sense*. An invoice that breaks any of them is refused with `422` and is not stored.

| Rule | Issue code |
| --- | --- |
| `subtotal >= 0` | `NEGATIVE_AMOUNT` |
| `tax >= 0` | `NEGATIVE_AMOUNT` |
| `total >= 0` | `NEGATIVE_AMOUNT` |
| `subtotal + tax == total` | `TOTAL_MISMATCH` |
| `invoice_date <= today` (UTC) | `FUTURE_INVOICE_DATE` |
| `currency in {EUR, USD, GBP}` | `INVALID_CURRENCY` |
| `vendor + invoice_number` must not already exist | `DUPLICATE_INVOICE` |

`DUPLICATE_INVOICE` currently returns `422` alongside the other rules. Phase 12 gives it its
own `DuplicateInvoiceError` and promotes it to `409 Conflict`, which is the more accurate code
for "this conflicts with something that already exists."

All rules are evaluated on every request, so one response reports everything that is wrong:

```bash
curl -X POST http://127.0.0.1:8000/invoices -H 'Content-Type: application/json' \
  -d '{"invoice_number":"INV-9","vendor":"V","invoice_date":"2099-12-31",
       "currency":"XYZ","subtotal":"-5","tax":"-5","total":"9999"}'
```

```json
{"detail":[
  {"code":"NEGATIVE_AMOUNT","field":"subtotal","message":"subtotal must not be negative"},
  {"code":"NEGATIVE_AMOUNT","field":"tax","message":"tax must not be negative"},
  {"code":"TOTAL_MISMATCH","field":"total","message":"subtotal (-5) + tax (-5) must equal total (9999)"},
  {"code":"FUTURE_INVOICE_DATE","field":"invoice_date","message":"invoice_date 2099-12-31 is in the future"},
  {"code":"INVALID_CURRENCY","field":"currency","message":"currency must be one of EUR, GBP, USD"}
]}
```

Currency matching is case-sensitive: `"eur"` is rejected. Normalizing input casing is Phase
18's job, where Excel rows arrive in whatever form a spreadsheet happened to contain.

### Two kinds of 422

Schema failures and business failures share the same status code but carry different bodies,
so a client tells them apart by which keys are present:

| Failure | Body shape |
| --- | --- |
| Schema (Pydantic) | `{"type", "loc", "msg", "input"}` |
| Business rule | `{"code", "field", "message"}` |

Both mean "well-formed JSON the server will not process." Unifying them, if it is ever worth
doing, belongs to Phase 12, which owns exception-to-HTTP translation.

### Status codes

| Code | When |
| --- | --- |
| `201 Created` | Invoice created |
| `200 OK` | Invoice or list returned |
| `404 Not Found` | No invoice with that ID |
| `422 Unprocessable Entity` | Request failed schema validation |

### Examples

Create an invoice:

```bash
curl -i -X POST http://127.0.0.1:8000/invoices \
  -H 'Content-Type: application/json' \
  -d '{"invoice_number":"INV-001","vendor":"ABC GmbH","invoice_date":"2026-09-04",
       "currency":"EUR","subtotal":"1000.00","tax":"190.00","total":"1190.00"}'
```

```text
HTTP/1.1 201 Created
```
```json
{"id":1,"invoice_number":"INV-001","vendor":"ABC GmbH","invoice_date":"2026-09-04","currency":"EUR","subtotal":"1000.00","tax":"190.00","total":"1190.00","status":"DRAFT","created_at":"2026-09-04T16:29:41.764554Z"}
```

The server assigns the `id`. List them, then fetch one:

```bash
curl http://127.0.0.1:8000/invoices
curl http://127.0.0.1:8000/invoices/1
```

A malformed submission names the offending field:

```bash
curl -X POST http://127.0.0.1:8000/invoices -H 'Content-Type: application/json' \
  -d '{"nonsense":true}'
```

```json
{"detail":[{"type":"missing","loc":["body","invoice_number"],"msg":"Field required"}, ...]}
```

Requesting an invoice that does not exist:

```bash
curl -i http://127.0.0.1:8000/invoices/999
```

```text
HTTP/1.1 404 Not Found
```
```json
{"detail":"Invoice not found"}
```

## Sending money

**Send amounts as JSON strings, not JSON numbers.** Both are accepted, but only strings
survive the round trip intact:

| Sent | Returned |
| --- | --- |
| `"subtotal": "1000.00"` | `"1000.00"` — exact |
| `"subtotal": 1000.00` | `"1000.0"` — scale lost |
| `"tax": "0.10"` | `"0.10"` — exact |
| `"tax": 0.10` | `"0.1"` — scale lost |

A JSON *number* is parsed as a binary float before it can become a `Decimal`, and the float
has no memory of how many digits were written. A JSON *string* is handed to `Decimal`
verbatim. For invoices the difference is whether `1000.00` still reads as an amount in cents.

Responses always serialize amounts as strings, because that is the only JSON type that can
carry a decimal exactly.

## Known limitations

Every item below is a deliberate consequence of the current phase, not an oversight. The
playbook introduces each fix only once the problem is visible.

| Limitation | Try it | Resolved by |
| --- | --- | --- |
| Duplicate detection is check-then-insert with no constraint underneath, so two *concurrent* requests can both pass the check and both write | see below | Phase 33 — idempotency |
| Amounts with more than 2 decimal places are **silently rounded** by the database, which can break an invoice that passed validation | `POST` `subtotal:"0.005", tax:"0.005", total:"0.010"` → `201`, stored as `0.01 + 0.01 = 0.01` | unowned — see below |
| A database error surfaces as a bare `500` | `POST` an amount above `9999999999.99` → `500 Internal Server Error` | Phase 12 — exception handling |
| Nothing ever modifies an invoice, so `updated_at` always equals `created_at` | — | Phase 39 — review workflow |
| An invoice is a header only; there are no line items, so the totals are asserted rather than derived | nothing sums to `subtotal` | Phase 15 — invoice items |

One thing worth knowing about the current validation: **unknown fields are ignored, not
rejected.** `{"...": ..., "nonsense": true}` succeeds and `nonsense` is simply dropped. This
is Pydantic's default; a typo like `vendour` therefore surfaces as *"vendor: Field
required"* rather than as a complaint about `vendour`.

### The duplicate race, in detail

`InvoiceService.create()` checks for a duplicate and then inserts. Nothing in the database
enforces uniqueness, so the check can go stale between those two steps:

```text
session A: find_by_vendor_and_invoice_number -> None
session B: find_by_vendor_and_invoice_number -> None
session A: INSERT  -> id 1
session B: INSERT  -> id 2      two rows, same vendor + invoice_number
```

That interleaving was reproduced deliberately and does produce two rows. The window is narrow
— `create()` re-runs the check immediately before writing — and 12 concurrent identical `POST`
requests produced 1 × `201` and 11 × `422`, so it does not show up under ordinary load. It is
still a correctness gap, not a performance one.

The real fix is a unique constraint on `(vendor, invoice_number)`, which makes the database
the arbiter rather than a prior `SELECT`. That means a migration plus catching `IntegrityError`
and turning it into the same issue — which wants Phase 12's exception handling to do cleanly.

### The rounding gap, in detail

Business rules run on the Pydantic `Decimal` values. The database applies `NUMERIC(12,2)`
*afterwards*, and PostgreSQL rounds to scale rather than refusing:

```text
submitted   subtotal 0.005 + tax 0.005 == total 0.010    validation passes
stored      subtotal 0.01  + tax 0.01  != total 0.01     no longer true
```

Verified against the table: `SELECT (subtotal + tax = total)` returns `f` for that row. An
invoice can therefore satisfy `TOTAL_MISMATCH` on the way in and violate it in storage.

The fix is a business rule — amounts must carry at most two decimal places — which belongs
with the other rules rather than being smuggled in as part of a persistence change. It is
recorded here rather than fixed silently.

## Project layout

```text
.
├── app/
│   ├── main.py              # FastAPI app; mounts the routers
│   ├── db/
│   │   ├── base.py          # Base — the declarative registry
│   │   └── session.py       # DATABASE_URL, engine, SessionLocal
│   ├── models/
│   │   └── invoice.py       # Invoice — the "invoices" table
│   ├── repositories/
│   │   └── invoice_repository.py   # All invoice SQL lives here
│   ├── routers/
│   │   └── invoices.py      # HTTP only: routes, status codes
│   ├── schemas/
│   │   └── invoice.py       # InvoiceCreate, InvoiceRead
│   └── services/
│       └── invoice_service.py      # Business rules and invoice creation
├── migrations/
│   ├── env.py               # Alembic config; reads DATABASE_URL
│   └── versions/            # One file per schema change
├── alembic.ini
├── requirements.txt         # Pinned dependencies
├── docs/
│   └── learning-log.md
└── InvoiceFlow_Claude_Code_Implementation_Playbook.md
```

`models/` and `schemas/` both contain a file called `invoice.py`, and the distinction
matters: `models/invoice.py` is the SQLAlchemy table, `schemas/invoice.py` is the pair of
Pydantic models describing what crosses the API boundary. They carry similar fields today and
are free to diverge — a column can exist without being exposed.

The split happened in Phase 5 for one reason: `main.py` had reached 159 lines and held five
unrelated things at once — the app object, both schemas, the store, the business rules, and
every route. It was not done because layered folders are inherently better. A project this
size does not need them until reading it becomes annoying, and that is the signal to act on.

Each layer has one job, and the boundaries are rules rather than conventions:

```text
Router       ->  InvoiceService   ->  InvoiceRepository  ->  PostgreSQL
transport        business behavior    persistence
```

> **The repository handles persistence only.** It does not decide whether totals are valid,
> whether a currency is supported, or whether an invoice should be accepted. Handed a
> nonsense invoice, it stores the nonsense faithfully.

> **The service knows nothing about HTTP.** `app/services/invoice_service.py` imports only
> `datetime` and other `app` modules — importing it loads no FastAPI module at all. That is
> what lets the business rules be exercised without a running server, and what will let the
> Excel importer (Phase 20) and the document extractor (Phase 38) apply the same rules to
> invoices that never arrived over HTTP.

The price of that independence is visible in `InvoiceService.create()`, which returns
`(invoice, issues)` rather than raising: it cannot raise `HTTPException` without depending on
the web framework. Phase 12 introduces domain exceptions and takes the tuple away.

Note what is *still* not separated: routes open sessions and construct the service and
repository by hand. Phase 10 replaces that with injected dependencies.
