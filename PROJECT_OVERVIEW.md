# InvoiceFlow — Project Overview

**Status:** Phase 21 of 50 complete (tag `v0.22-import-errors`). This document describes the
system as it stands today — what it does, how a request moves through it, and the database
underneath. For the phase-by-phase story of *why* each piece exists, see
[docs/learning-log.md](docs/learning-log.md); for setup and usage, see
[README.md](README.md).

---

## 1. What it does

InvoiceFlow ingests invoices two ways and validates both the same way:

- **Manually**, one at a time, as a JSON request — `POST /invoices`.
- **In bulk**, via an Excel workbook — `POST /imports`, using the template the API itself
  publishes at `GET /templates/invoice-import`.

Every invoice, however it arrives, is checked against the same business rules — non-negative
amounts, totals that add up, a supported currency, a non-future date, no duplicates — and, if
it has line items, that the declared header totals reconcile against the sum of the lines.
An invoice that fails is rejected with a machine-readable reason; an invoice that passes is
persisted as `VALID`.

**What is not built yet:** authentication, multi-tenancy, updating or deleting an invoice,
PDF/image intake, background processing (imports run synchronously inside the request), file
storage (uploaded workbooks are parsed and discarded), and any deployment beyond a local
PostgreSQL instance. These are later phases (21–50) of the project's roadmap, not omissions.

---

## 2. How it works

### 2.1 The layers

```
Router  →  Service  →  Repository  →  PostgreSQL
HTTP        business      persistence
concerns    rules
```

Each layer has exactly one job, enforced as a rule rather than a convention:

| Layer | Knows about | Must not know about |
| --- | --- | --- |
| **Router** (`app/routers/`) | HTTP: paths, status codes, request/response schemas | SQL, business rules |
| **Service** (`app/services/`) | Business rules, orchestration | FastAPI, HTTP status codes |
| **Repository** (`app/repositories/`) | Persistence: SQLAlchemy sessions and queries | Whether the data is *valid* |

The service layer is deliberately framework-agnostic: it raises plain Python exceptions
(`app/core/exceptions.py`), never `HTTPException`. A single module,
`app/core/error_handlers.py`, is the only place in the codebase that knows both "what went
wrong" and "what HTTP status that means." This is what lets the exact same validation logic
serve two entry points — see §2.3.

### 2.2 Manual invoice flow

```
POST /invoices  →  InvoiceService.create()
                      ├─ validate()          six business rules, pure function
                      ├─ duplicate check      vendor + invoice_number, via the repository
                      ├─ derive line amounts   quantity × unit_price, tax on top
                      └─ InvoiceRepository.create()   one INSERT, cascaded to items
```

`InvoiceService.create()` either returns a persisted `Invoice` or raises one of
`InvoiceValidationError` / `DuplicateInvoiceError`. The router's only job is to call it and
let the exception handlers translate the outcome into a response.

### 2.3 Excel import flow

```
POST /imports (multipart file)
   │
   ├─ 1. Structural check          app/services/excel_template.py column list
   │      (right extension, opens as .xlsx, "Invoices" sheet, all 11 columns present)
   │      fails → 422, no ImportJob is even created
   │
   ├─ 2. Parse rows                app/services/excel_parser.py
   │      each row → ParsedRow (typed) or RowError (per bad cell)
   │
   ├─ 3. Group into invoices       app/services/excel_grouper.py
   │      rows sharing vendor + invoice_number → one GroupedInvoice + its GroupedItems
   │      cross-row disagreement (e.g. two rows, two currencies) → InvoiceError
   │
   ├─ 4. Validate & persist        app/services/import_service.py → to_invoice_create()
   │      each GroupedInvoice is converted to the *same* InvoiceCreate schema a JSON
   │      request uses, then passed to the *same* InvoiceService.create() call
   │
   └─ 5. Report                    counts + persisted ImportError rows
          GET /imports/{import_id} returns the tally
```

**The one fact that matters most:** step 4 does not reimplement any business rule. It builds
an `InvoiceCreate` object from the parsed spreadsheet data and calls
`InvoiceService.create()` — the identical code path a manual JSON request goes through. This
is enforced by a test (`test_excel_and_json_reject_an_invoice_identically`) that submits the
same broken invoice both ways and asserts the returned error codes are identical.

A file can be *structurally* perfect while every invoice inside it is business-nonsense
(negative quantities, invalid currency, mismatched totals) — that still returns `201`, because
structural validation and business validation are different questions asked at different
stages. The report's counts, not the HTTP status, carry the outcome.

### 2.4 Error handling

Every failure becomes a plain Python exception, mapped to HTTP in exactly one file:

| Exception | Status | Meaning |
| --- | --- | --- |
| `InvoiceNotFoundError` | 404 | No invoice with that id |
| `ImportJobNotFoundError` | 404 | No import with that id |
| `DuplicateInvoiceError` | 409 | `vendor + invoice_number` already exists |
| `InvoiceValidationError` | 422 | One or more business rules failed |
| `ImportFileError` | 422 | The uploaded file is not structurally usable |
| `sqlalchemy.exc.DataError` | 422 | e.g. an amount too large for its column |
| *(anything else)* | 500 | Unhandled — logged, and the client gets a generic message |

422 responses carry a `detail` list of `{code, field, message}` objects, so a client (or a
spreadsheet user) can act on the specific problem rather than parsing prose.

### 2.5 Configuration and logging

Settings (`app/core/config.py`) are read once from environment variables / `.env` via
`pydantic-settings` — database URL, environment name, log level — with no other module
reading `os.environ` directly. Logging (`app/core/logging.py`) emits structured JSON in
production and human-readable lines in development, driven by the same settings object.

---

## 3. Database design

PostgreSQL, four tables, managed by five Alembic migrations applied in a single linear chain:

```
1187a8364717  create invoices table
      ↓
e4fd0b79bf05  add updated_at to invoices
      ↓
dc1930268747  add invoice_items
      ↓
d6043a70b7c2  add import_jobs
      ↓
2db755e1146b  add import counts and import_errors   (current head)
```

### 3.1 Entity relationships

```
invoices  (1) ──< (N)  invoice_items        ON DELETE CASCADE
import_jobs (1) ──< (N)  import_errors       ON DELETE CASCADE

invoices  ⋯⋯⋯⋯⋯⋯⋯⋯⋯⋯⋯⋯  import_jobs         no foreign key — see note below
```

**Known gap:** an invoice created by an import carries no reference back to the
`import_jobs` row that created it. There is no `import_job_id` column on `invoices`. This
means "which invoices did import X create?" cannot currently be answered from the schema —
only "how many did it create," from the counts on `import_jobs`. Recorded here rather than
hidden; it is a candidate fix for a later phase.

### 3.2 `invoices`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER` PK | auto-incrementing |
| `invoice_number` | `VARCHAR(100)` | not unique alone — see duplicate note below |
| `vendor` | `VARCHAR(255)` | |
| `invoice_date` | `DATE` | must not be in the future (business rule) |
| `currency` | `VARCHAR(3)` | one of `EUR`, `USD`, `GBP` (business rule, not a DB constraint) |
| `subtotal` | `NUMERIC(12,2)` | see §3.5 on why `NUMERIC` |
| `tax` | `NUMERIC(12,2)` | |
| `total` | `NUMERIC(12,2)` | must equal `subtotal + tax` (business rule) |
| `status` | `VARCHAR(20)` | currently always `"VALID"` — the only value ever written |
| `created_at` | `TIMESTAMPTZ` | |
| `updated_at` | `TIMESTAMPTZ` | set equal to `created_at` on insert; nothing updates an invoice yet |

### 3.3 `invoice_items`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER` PK | |
| `invoice_id` | `INTEGER` FK → `invoices.id`, indexed | `ON DELETE CASCADE` |
| `description` | `VARCHAR(500)` | the sheet's "item" column |
| `quantity` | `NUMERIC(12,3)` | 3 decimal places — quantities can be fractional (hours, kg) |
| `unit_price` | `NUMERIC(12,2)` | |
| `tax_rate` | `NUMERIC(5,2)` | a percentage: `19` means 19%, not `0.19` |
| `line_subtotal` | `NUMERIC(12,2)` | **derived and stored**, not recomputed on read |
| `line_tax` | `NUMERIC(12,2)` | derived: `line_subtotal × tax_rate / 100` |
| `line_total` | `NUMERIC(12,2)` | derived: `line_subtotal + line_tax` |

Line amounts are calculated once at creation and stored permanently, even though they could
be recomputed from `quantity`, `unit_price`, and `tax_rate`. An invoice is a record of what
was agreed at the time; if a tax rate were later reinterpreted, recomputing on read would
silently rewrite history.

### 3.4 `import_jobs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `VARCHAR(32)` PK | a prefixed string, e.g. `imp_a7f3c2e1d901` — not an integer, see §3.6 |
| `filename` | `VARCHAR(255)` | as uploaded |
| `status` | `VARCHAR(24)` | `"COMPLETED"` once processed (see below) |
| `created_at` | `TIMESTAMPTZ` | |
| `total_rows` | `INTEGER` | non-blank data rows in the sheet |
| `valid_rows` | `INTEGER` | rows that parsed successfully |
| `invalid_rows` | `INTEGER` | rows that failed to parse |
| `invoices_found` | `INTEGER` | distinct `vendor + invoice_number` groups |
| `invoices_created` | `INTEGER` | groups that became persisted invoices |
| `invoices_failed` | `INTEGER` | groups rejected by validation or grouping |
| `duplicate_invoices` | `INTEGER` | groups that already existed |

`status` is `COMPLETED` even when every invoice inside the file failed — it means *processing
finished*, not *everything succeeded*. The seven counts carry the actual outcome. This mirrors
the two-tier design throughout the project: a status/HTTP code answers "did the operation run
to completion," and a body of counts or issue codes answers "what actually happened."

### 3.5 `import_errors`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER` PK | |
| `import_id` | `VARCHAR(32)` FK → `import_jobs.id`, indexed | `ON DELETE CASCADE` |
| `scope` | `VARCHAR(16)` | `"row"` or `"invoice"` |
| `row_number` | `INTEGER`, nullable | set for row-scoped errors |
| `invoice_number` | `VARCHAR(100)`, nullable | set for invoice-scoped errors |
| `vendor` | `VARCHAR(255)`, nullable | |
| `code` | `VARCHAR(48)` | e.g. `INVALID_CURRENCY`, `MISSING_REQUIRED_FIELD` |
| `field` | `VARCHAR(64)`, nullable | the specific field at fault, where applicable |
| `message` | `VARCHAR(500)` | human-readable, truncated to 500 characters |

Errors are persisted rather than recomputed on demand, because the uploaded file itself is
discarded after processing — there is nothing left to re-parse if a client asks for the
report later.

### 3.6 Two identifier styles, deliberately

`invoices.id` and `invoice_items.id` are ordinary auto-incrementing integers. `import_jobs.id`
is a prefixed random string (`imp_` + 12 hex characters). This is intentional, not an
inconsistency that slipped through: import ids are handed to external users in API responses
and referenced later (`GET /imports/{import_id}`), so a non-sequential, self-describing
identifier avoids leaking a count of imports and avoids collisions if job creation ever moves
off a single database sequence (e.g. distributed workers in a later phase).

### 3.7 Why `NUMERIC` instead of floating point

Every monetary and quantity column uses PostgreSQL's `NUMERIC(precision, scale)` rather than
`FLOAT`/`DOUBLE PRECISION`. Binary floating point cannot represent most decimal fractions
exactly (`0.1 + 0.2 ≠ 0.3` in IEEE 754), which is unacceptable for money. `NUMERIC` stores an
exact base-10 value. The trade-off: `NUMERIC` silently *rounds* values beyond its declared
scale rather than rejecting them (e.g. a value with 3 decimal places written to a
`NUMERIC(12,2)` column rounds to 2) — this is a known, currently unowned gap; the application
layer does not yet enforce scale before the database does.

### 3.8 Cascading deletes

Both parent/child pairs (`invoices`→`invoice_items`, `import_jobs`→`import_errors`) use
`ON DELETE CASCADE` at the database level *and* `cascade="all, delete-orphan"` at the ORM
level. Deleting a parent row through raw SQL or through the ORM both correctly remove its
children — there is no path that leaves an orphaned line item or error row.

---

## 4. Current API surface

| Method | Path | Purpose | Success | Failure |
| --- | --- | --- | --- | --- |
| `GET` | `/` | Liveness check | 200 | — |
| `POST` | `/invoices` | Create one invoice | 201 | 422 (validation), 409 (duplicate) |
| `GET` | `/invoices` | List all invoices | 200 | — |
| `GET` | `/invoices/{invoice_id}` | Fetch one invoice | 200 | 404 |
| `GET` | `/templates/invoice-import` | Download the `.xlsx` import template | 200 | — |
| `POST` | `/imports` | Upload and process a workbook | 201 | 422 (structural) |
| `GET` | `/imports/{import_id}` | Fetch an import's report (the counts) | 200 | 404 |
| `GET` | `/imports/{import_id}/errors` | Fetch the paginated, actionable error detail behind those counts | 200 | 404 |

(404/409/500 are produced by the exception-handler layer described in §2.4 and are not
declared per-route in the OpenAPI schema, since they are cross-cutting rather than
route-specific. `/imports/{import_id}/errors` also accepts `?limit=` (1–1000, default 100)
and `?offset=` (≥ 0, default 0), validated by FastAPI itself.)

---

## 5. Where it stops today

Everything below is a stated future phase in the project roadmap, not a gap discovered here:

- **Explicit transaction boundaries** — each invoice in a bulk import currently commits on
  its own success/failure; there is no larger transaction wrapping a whole import.
- **File storage** — uploaded workbooks are parsed in memory and never saved; a failed
  import cannot be re-processed without re-uploading.
- **Asynchronous processing** — imports run to completion inside the HTTP request; a very
  large file blocks the request for as long as processing takes.
- **PDF / image invoice intake, OCR** — only structured Excel and JSON are accepted.
- **Authentication, authorization, multi-tenancy** — every endpoint is currently open.
- **Editing or deleting invoices** — `updated_at` exists on the schema but nothing ever
  changes an invoice after creation.
- **Containerization and cloud deployment** — the application runs against a local
  PostgreSQL instance; there is no Docker, CI/CD, or infrastructure-as-code yet.

The duplicate-invoice check (`vendor + invoice_number`) is also enforced only at the
application layer via a query-then-insert pattern, not by a database `UNIQUE` constraint —
under concurrent requests this is a known race condition, tracked as a later fix rather than
resolved here.
