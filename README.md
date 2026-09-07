# InvoiceFlow

A backend platform for ingesting, validating, processing, and tracking invoices.

**Current status:** Phase 24 — deployed, once, on purpose. **The application ran on an AWS
Lightsail instance in Frankfurt and answered `200 OK` from ~25 countries; the instance was then
deleted, and [the write-up](docs/deployment-lightsail.md) is what it left behind.** Behind it:
`docker compose up` starts FastAPI, PostgreSQL, and the migration that builds the schema with
nothing manually installed; a single invoice failing at the database level can no longer take
the rest of an import down with it; a readable error report behind the counts; uploading a
spreadsheet creates invoices; parsing, grouping, structural checks; the published import
contract; invoices with line items whose amounts are derived and reconciled; three layers wired
by FastAPI; a validated settings object; domain exceptions translated to HTTP in one place;
structured logging; and 187 tests. A permanent, production-shaped deployment is addressed by
later phases of [the implementation
playbook](InvoiceFlow_Claude_Code_Implementation_Playbook.md) — Lightsail was explicitly a
learning exercise, not the destination.

## Requirements

Either of two ways to run this, not both at once for the same purpose:

- **Docker + Docker Compose** — see [Docker](#docker) below. No local Python, PostgreSQL, or
  `uv` needed.
- **Local** — Python 3.12, [uv](https://docs.astral.sh/uv/) for environment and dependency
  management, PostgreSQL 16.

> The system Python on this machine ships without `pip` and without `ensurepip`, so
> `python3 -m venv` cannot bootstrap itself. `uv` handles both the virtual environment and
> the installs without needing `sudo`. This only matters for the local path — the Docker image
> is built from a base image where `pip` already works.

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

The connection string comes from the `DATABASE_URL` setting — see
[Configuration](#configuration) below.

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

## Configuration

Every setting lives in [app/core/config.py](app/core/config.py) and is documented in
[.env.example](.env.example). Nothing else in the codebase reads the environment.

| Setting | Default | Read by |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://invoiceflow:invoiceflow@localhost:5432/invoiceflow` | the engine and Alembic |
| `APP_ENV` | `development` | the log format — human-readable here, JSON elsewhere |
| `LOG_LEVEL` | `INFO` | the minimum level that reaches stdout |

Resolution order, first match wins:

```text
1. an environment variable
2. a key in .env
3. the default in app/core/config.py
```

So both of these work, and neither touches source:

```bash
DATABASE_URL="postgresql+psycopg://user:pass@host:5432/other" uv run uvicorn app.main:app

cp .env.example .env    # then edit it; .env is gitignored
```

Settings are **validated at import time**, so a mistake stops the process immediately with a
message naming the field:

```bash
LOG_LEVEL=VERBOSE uv run uvicorn app.main:app
# log_level
#   Input should be 'DEBUG', 'INFO', 'WARNING', 'ERROR' or 'CRITICAL'
```

`invoiceflow/invoiceflow` is a local development credential, not a secret. `.env` is
gitignored precisely so it can hold real values locally without being committed; production
credentials belong in a secret store, which Phase 41 and Phase 45 cover.

## Excel import template

```bash
curl -OJ http://127.0.0.1:8000/templates/invoice-import
# invoiceflow-invoice-import-template-v1.xlsx
```

The template is a **public contract**, not a convenience. It defines exactly what an import
file must look like, and from Phase 17 the upload validator checks arriving files against the
same definition — the column list in
[app/services/excel_template.py](app/services/excel_template.py) is the only copy, so what we
hand out and what we accept cannot drift apart. The workbook is generated per request rather
than committed as a binary for the same reason.

### Columns

Every column is required on **every row**. One row per line item, so an invoice with three
lines takes three rows, repeating the invoice-level columns on each.

| Column | Format | Notes |
| --- | --- | --- |
| `invoice_number` | text | With `vendor`, groups rows into one invoice |
| `vendor` | text | Part of the grouping key |
| `invoice_date` | `YYYY-MM-DD` | Not in the future |
| `item` | text | The API calls this `description` |
| `quantity` | number, ≤3 decimals | Greater than 0; may be fractional |
| `unit_price` | number, 2 decimals | Before tax |
| `tax_rate` | number, 0–100 | **19 means 19%**, not 0.19 |
| `currency` | `EUR`, `USD`, `GBP` | Uppercase |
| `declared_subtotal` | number, 2 decimals | Checked against the lines |
| `declared_tax` | number, 2 decimals | Checked against the lines |
| `declared_total` | number, 2 decimals | Checked against the lines |

Two column names are mappings rather than passthroughs. `item` is the spreadsheet's word for
the API's `description`. And `declared_*` is doing real work: on a row those sit beside
per-line values, and the prefix says they are what the sender *claims* — Phase 20 checks them
against the sum of the lines, using the reconciliation [Phase 15
built](#line-items).

### Sheets

| Sheet | Contents |
| --- | --- |
| `Invoices` | The header row, and nothing else |
| `Instructions` | Column reference, formats, and a worked two-row invoice |

The data sheet is deliberately empty below the header. Anything left there is something a user
can forget to delete and then import as a real invoice, so the worked example lives on the
Instructions sheet where it cannot be mistaken for data.

### Versioning

The version appears in the filename **and** in the workbook, at `Instructions!B1`:

```text
invoiceflow-invoice-import-template-v1.xlsx
template_version    1
```

A file that has been renamed, emailed, or re-saved still identifies itself — which is exactly
the case where knowing matters. Phase 17 reads it back so an outdated template can be
reported as such, rather than failing on a missing column and leaving the user to guess.

Bump `TEMPLATE_VERSION` whenever the columns change.

## Uploading an import file

```bash
curl -X POST http://127.0.0.1:8000/imports -F "file=@march-invoices.xlsx"
```

```json
{"id":"imp_78fe620d94f6","filename":"march-invoices.xlsx","status":"UPLOADED",
 "created_at":"2026-09-05T19:59:42.800405+03:30"}
```

The response is the import report — the same thing `GET /imports/{id}` returns.

### Structure is checked before contents

The upload is rejected outright if the file is not a readable workbook with the right columns.
Only then are the rows parsed, grouped and validated. Keeping the two apart is what stops an
import report being an unreadable mix of "column missing" and "invoice INV-1008 is a
duplicate" — and it means a `422` here always means *the file*, never the invoices inside it.

| Check | Issue code |
| --- | --- |
| Filename ends in `.xlsx` | `INVALID_FILE_TYPE` |
| The upload is not empty | `EMPTY_FILE` |
| It opens as a workbook | `UNREADABLE_WORKBOOK` |
| It has an `Invoices` sheet | `WORKSHEET_MISSING` |
| Every required column is present | `MISSING_COLUMNS` |
| There is at least one data row | `NO_DATA_ROWS` |

Structural failures return `422` with the same `{code, field, message}` shape as business
rules, so a client parses one kind of error body. Unlike business rules these stop at the
first problem — there is nothing useful to say about the columns of a file that is not a
workbook.

The messages are meant to be readable by whoever prepared the file:

```text
missing required column(s): vendor. This file was made from template v0;
the current template is v1.
```

That version hint appears **only** when the columns fail. A file whose columns are right
imports whatever version it declares, including none — hand-built files have no version cell
and are perfectly valid.

### Two id styles

`ImportJob.id` is a prefixed string (`imp_78fe620d94f6`); `Invoice.id` is an integer. That is
a real inconsistency, chosen deliberately: an import id travels through URLs, logs and support
conversations, where `imp_78fe620d94f6` is unambiguous about what it refers to and needs no
parsing at the boundary. Invoice ids never left the database's control.

## The import report

```bash
curl http://127.0.0.1:8000/imports/imp_61f8cc06a072
```

```json
{
  "id": "imp_61f8cc06a072", "filename": "1-VALID-upload-me.xlsx",
  "status": "COMPLETED",
  "total_rows": 2, "valid_rows": 2, "invalid_rows": 0,
  "invoices_found": 1, "invoices_created": 1,
  "invoices_failed": 0, "duplicate_invoices": 0
}
```

### The pipeline

```text
upload -> structure -> parse rows -> group into invoices -> InvoiceService.create()
```

That last step is the point. Imported invoices go through **the same
`InvoiceService.create()`** a JSON request goes through — not similar rules, the same object,
raising the same domain exceptions. `tests/test_import_report.py` asserts that the identical
invoice submitted both ways produces identical issue codes, so reimplementing a rule in the
import path fails the suite.

### Reading the counts

Row-level and invoice-level counts answer different questions: 57 bad rows might be 57 broken
invoices or one invoice with 57 lines.

| | |
| --- | --- |
| `total_rows` | non-blank data rows — blank rows are not counted |
| `valid_rows` / `invalid_rows` | rows that parsed, and rows that did not |
| `invoices_found` | distinct `vendor + invoice_number` groups |
| `invoices_created` | stored successfully |
| `invoices_failed` | rejected by a business rule, or by grouping |
| `duplicate_invoices` | already existed |

Two invariants always hold:

```text
total_rows     = valid_rows + invalid_rows
invoices_found = invoices_created + invoices_failed + duplicate_invoices
```

### `COMPLETED` does not mean everything worked

It means processing ran to the end. The counts carry the outcome — an import with 57 bad rows
is still `COMPLETED`. `FAILED` means processing itself broke. `PARTIALLY_COMPLETED` is unused
until Phase 32, where a background worker can genuinely stop halfway.

### A repeated invoice number inside one file is not a duplicate

It is another line item. Grouping is by `vendor + invoice_number`, so two rows sharing both
are two lines of one invoice — which is exactly how a three-line invoice is expressed.

Duplicates arise against invoices **already stored**. Re-uploading the same file is therefore
safe:

```text
first upload  -> created=1  duplicates=0
second upload -> created=0  duplicates=1
```

### One bad invoice does not cost the good ones

Each invoice is stored on its own, so a file of ten invoices with one broken imports the other
nine. Phase 22 makes that boundary deliberate rather than a side effect of where the commit
happens to be.

Errors are persisted as they are produced — the uploaded file is discarded, so an error not
written down is gone.

### Reading what went wrong

```bash
curl "http://127.0.0.1:8000/imports/imp_628b4ef2fbbd/errors"
```

```json
{
  "total": 4, "limit": 100, "offset": 0,
  "errors": [
    {
      "scope": "row", "row_number": 4, "invoice_number": "INV-BADROW",
      "vendor": "Acme Ltd", "code": "INVALID_NUMBER", "field": "quantity",
      "message": "'two' is not a number",
      "summary": "Row 4 → 'two' is not a number"
    },
    {
      "scope": "invoice", "row_number": null, "invoice_number": "INV-SPLIT",
      "vendor": "Acme Ltd", "code": "INCONSISTENT_INVOICE_FIELD", "field": "currency",
      "message": "rows of this invoice disagree about currency: row 5 says EUR; row 6 says USD",
      "summary": "Invoice INV-SPLIT → rows of this invoice disagree about currency: row 5 says EUR; row 6 says USD"
    }
  ]
}
```

Read as prose, one file with several kinds of problem in it:

```text
Row 4 → 'two' is not a number
Invoice INV-SPLIT → rows of this invoice disagree about currency: row 5 says EUR; row 6 says USD
Invoice INV-BADROW → row(s) 4 could not be read, so no invoice could be built from them
Invoice INV-BADCURR → currency must be one of EUR, GBP, USD
```

That is what the counts on the report were standing in for. `invoices_failed: 3` says *how
many*; this endpoint says *which ones, and why*, so someone can go back to the spreadsheet and
actually fix it.

**`scope` tells you which identifying field to trust.** A `"row"` error always carries a
`row_number`; an `"invoice"` error never does, because there is no single row to point at —
grouping or a business rule failed across the whole invoice. `invoice_number`/`vendor` may
still be populated on a row error when the identity cells were themselves readable — Phase 19
needs that to attribute a failed row to its invoice, so it is not a leak between the two
scopes, it is the same information serving two purposes.

**`code` and `field` for software, `summary` for people.** Every other error surface in this
API returns `{code, field, message}` — nothing here abandons that. `summary` is rendered once
at the response boundary from those same fields, so a UI can display it directly while
anything automated still filters on `code`.

**A structurally invalid invoice can produce two stored errors from one bad cell**, and that
is correct rather than duplicated noise: `INV-BADROW`'s row 4 fails to parse (`INVALID_NUMBER`
on `quantity`), and because that row can never become a line item, grouping separately reports
the invoice as `INCOMPLETE_INVOICE`. Two different facts — the cell is unreadable, and the
invoice is missing a line as a consequence.

**Paginated**, because a 100,000-file historical import (Phase 40) could produce far more
errors than fit in one response:

```bash
curl "http://127.0.0.1:8000/imports/imp_.../errors?limit=5&offset=10"
```

`total` always reflects the whole import, not just the page returned, so a client can tell
"10 of 943" from "10 of 10" without a second request. Default `limit` is 100; `limit`/`offset`
are validated by FastAPI itself (`limit` 1–1000, `offset` ≥ 0) — no custom bounds-checking
needed. An import with zero errors returns `200` and an empty list, not `404`; `404` is
reserved for an import id that does not exist at all.

## Transaction boundaries

Two separate claims, both verified against real data before this phase changed anything.

**An invoice and its line items already succeed or fail together.** They go through one
`session.add()` and one `session.commit()`, so a failed item insert cannot leave a
half-created invoice header behind. Confirmed by forcing an item-level `NUMERIC(12,2)`
overflow (the header amounts stay in range; only one item's `unit_price` is too large) and
checking the database afterward — zero rows in either table.

**One invoice's database-level failure used to abort the rest of an import.** Before this
phase, `_process()` caught business-rule failures and duplicates per invoice, but not a
failure at the database itself. Reproduced directly: a three-invoice file — good, an invoice
whose `unit_price` overflows `NUMERIC(12,2)`, good again — and the third invoice was **never
even attempted**:

```text
INV-BEFORE  -> persisted (committed before the failure)
INV-DBFAIL  -> correctly did not persist
INV-AFTER   -> never attempted -- a valid invoice, silently skipped

ImportJob   -> stuck at status="UPLOADED", every count at 0, forever
POST /imports -> a bare 422 for the whole upload, though INV-BEFORE had already succeeded
```

A client retrying that exact file would then see `INV-BEFORE` rejected as a duplicate, with
no way to have known it succeeded the first time.

**Fixed the same way business-rule failures already were:** catch the failure per invoice,
roll back the session (a failed commit leaves the session unusable until this runs —
verified directly, not assumed), record it, and move on to the next invoice:

```text
POST /imports (same three-invoice file)
  -> 201, status COMPLETED
  invoices_created: 2   invoices_failed: 1

invoices table -> INV-BEFORE, INV-AFTER   (both persisted)
GET /imports/{id}/errors -> Invoice INV-DBFAIL → AMOUNT_OUT_OF_RANGE
```

Same exception (`sqlalchemy.exc.DataError`), same `AMOUNT_OUT_OF_RANGE` code, whether it
arrives as one JSON request (Phase 12) or as one row inside a much larger file — one failure,
one meaning, regardless of how it arrived.

The fix is deliberately narrow: only `DataError` is caught here, matching what Phase 12
already handles for a single invoice. A genuinely unexpected exception still aborts the
request and surfaces through the 500 handler — see Known limitations below for what that
currently leaves unresolved.

## Row parsing

A cell is not a value. Excel hands back a float where you wanted a decimal, a `datetime` where
you wanted a date, and a string with a trailing space nobody can see.
[app/services/excel_parser.py](app/services/excel_parser.py) is the boundary where that
becomes typed data — nothing downstream has to think about cells again.

### Normalisation

| Cell contains | Becomes | |
| --- | --- | --- |
| `"  ABC GmbH  "` | `"ABC GmbH"` | whitespace stripped everywhere |
| `"  eur "` | `"EUR"` | the business rule is case-sensitive on purpose; this is where casing is fixed |
| `datetime(2026,1,15)` | `date(2026,1,15)` | a date-formatted cell |
| `"2026-01-15"` | `date(2026,1,15)` | a text cell |
| `0.1` (float) | `Decimal("0.1")` | via `str()` — `Decimal(0.1)` is `0.1000000000000000055…` |

### Row errors

| Situation | Code |
| --- | --- |
| A required cell is empty | `MISSING_REQUIRED_FIELD` |
| Not a date cell and not `YYYY-MM-DD` | `INVALID_DATE` |
| Not a number | `INVALID_NUMBER` |

Every non-blank row produces **exactly one** outcome — a typed row, or one or more errors,
never both. A row with three bad cells reports all three, so nobody has to resubmit to find
the next problem.

```text
row 2  PARSED   INV-001 | 'ABC GmbH' | 2026-01-15 | qty=2 | 'EUR'
row 4  (blank, skipped)
row 5  ERRORS
         INVALID_DATE      invoice_date  '15/01/2026' is not a date. Use YYYY-MM-DD.
         INVALID_NUMBER    quantity      'two' is not a number
```

Three deliberate choices:

**Ambiguous dates are refused.** `01/02/2026` is 2 January or 1 February depending on who
typed it. An invoice silently dated five weeks wrong is worse than one rejected, so only real
date cells and `YYYY-MM-DD` are accepted.

**Blank rows are skipped.** Excel keeps rows whose contents were deleted; a file with three
invoices and nine hundred leftovers should not produce nine hundred complaints. Row numbers
still match the sheet, so an error about "row 5" is the fifth row on screen.

**Columns are found by name, not position.** Reorder the columns and it still works — reading
by index would quietly put the vendor into the date field.

## Grouping rows into invoices

A spreadsheet does not contain rows, it contains invoices. One invoice with three lines takes
three rows, repeating its invoice-level columns on each.
[app/services/excel_grouper.py](app/services/excel_grouper.py) turns that repetition back into
a single thing.

```text
9 rows in            ->  2 invoices built from 5 lines, 2 flagged

INV-1001  ABC GmbH  2026-01-15  EUR  rows [2, 3, 4]
    row 2  Consulting   2 x 100 @19%
    row 3  Travel       1 x 50  @19%
    row 4  Materials    1 x 25  @19%
```

Rows are grouped by **`vendor + invoice_number`, compared exactly** — the same rule Phase 9's
duplicate check uses. Normalising differently here would mean the two disagree about what
counts as the same invoice.

### Cross-row consistency

Five columns describe the invoice rather than the line, and repeat on every row:
`invoice_date`, `currency`, `declared_subtotal`, `declared_tax`, `declared_total`. Every row of
an invoice must agree about all five.

| Situation | Code |
| --- | --- |
| Rows of one invoice disagree about an invoice-level field | `INCONSISTENT_INVOICE_FIELD` |
| One of an invoice's rows could not be parsed | `INCOMPLETE_INVOICE` |

```text
Invoice INV-3003 -> INCONSISTENT_INVOICE_FIELD
    rows of this invoice disagree about currency: row 7 says EUR; row 8 says USD

Invoice INV-4004 -> INCOMPLETE_INVOICE
    row(s) 10 could not be read, so this invoice is missing at least one line item
```

Two deliberate choices:

**No value wins a disagreement.** There is no first-row-wins or majority rule. The invoice is
rejected and every conflicting value is named with the row that claimed it.

**An invoice missing any line is rejected whole**, not built from the rows that survived.
Otherwise the error surfaces later as *"subtotal is 250.00 but lines sum to 200.00"*, sending
someone to hunt an arithmetic mistake when the cause is one unreadable cell — and they could
"fix" it by editing the totals, silently importing an invoice with a line missing.

Errors here name an **invoice**; parser errors name a **row**. Phase 21's report keeps that
distinction.

## Testing

```bash
uv run pytest
```

One command. No server, no `PYTHONPATH`, no fixtures to set up by hand.

```text
187 passed, 2 xfailed, 2 warnings in 4.54s
```

| File | Category | Tests |
| --- | --- | --- |
| `test_validation.py` | unit — pure rules, no database | 15 |
| `test_service.py` | service — rules plus duplicates | 8 |
| `test_repository.py` | integration — real SQL | 7 |
| `test_api.py` | API — `TestClient`, status codes | 20 |
| `test_architecture.py` | the layering rules, as assertions | 5 |
| `test_items.py` | line items — rules, derivation, storage | 24 |
| `test_template.py` | the import contract | 12 |
| `test_imports.py` | upload and structural validation | 17 |
| `test_parser.py` | row parsing and normalisation | 22 |
| `test_grouper.py` | grouping and cross-row consistency | 23 |
| `test_import_report.py` | the full import pipeline | 16 |
| `test_import_errors.py` | the error report, pagination | 12 |
| `test_transaction_boundaries.py` | atomicity, and one bad invoice not costing the rest | 7 |
| `test_concurrency.py` | the duplicate race (`xfail`) | 1 |

### Your development data is safe

Tests run against the same database the application uses, but nothing they do survives. Each
test gets a connection with an open transaction that is rolled back afterwards:

```python
session = Session(bind=connection, join_transaction_mode="create_savepoint")
```

`create_savepoint` is the part that matters. `InvoiceRepository.create()` calls
`session.commit()`, and without it that commit would end the outer transaction and leave
nothing to roll back. With it, those commits release savepoints instead.

The fixture also deletes existing rows at the start — inside the transaction — so every test
sees an empty table, and the rollback puts them straight back.

### The architecture tests

Five rules that earlier phases established are checked automatically rather than by eye:

- the service imports no FastAPI (Phase 12)
- domain exceptions import no FastAPI
- the router never imports `HTTPException` (Phase 12)
- the router contains no SQL calls (Phase 8)
- only `config.py` reads the environment (Phase 11)

They fail the moment someone reintroduces the coupling those phases removed.

### The two `xfail` tests

Two defects are known, documented, and deliberately unfixed. They are written as tests marked
`xfail` with `strict=True`, so they are executable documentation — and the day someone fixes
one, pytest reports `XPASS` and the suite fails until the marker is removed.

```text
XFAIL test_scale_rounding_preserves_totals  — the rounding gap
XFAIL test_concurrent_creates_cannot_both_succeed — the duplicate race
```

Both are described under [Known limitations](#known-limitations).

## Logging

The application logs four events to **stdout**. Nothing is written to a file — a container
writes to its output stream and lets the platform decide where that goes.

| Event | Level | Context |
| --- | --- | --- |
| `invoice_created` | `INFO` | `invoice_id`, `invoice_number`, `vendor` |
| `invoice_rejected` | `INFO` | `invoice_number`, `vendor`, `issue_codes` |
| `duplicate_detected` | `INFO` | `invoice_number`, `vendor` |
| `unexpected_error` | `ERROR` | `path`, `method`, `exception_type`, traceback |

The first three are logged by the **service**, not the router, because they are business
facts rather than HTTP facts — the Excel importer in Phase 20 will emit the same events with
no request in sight. `unexpected_error` is logged at the request boundary, where it belongs.

Rejections are `INFO`, not `WARNING`. A client sending something invalid and being told so is
a normal outcome; reserving the higher levels for things that need attention is what keeps
them meaningful.

`APP_ENV` chooses the format:

```text
development   INFO     invoice_created  invoice_id=1 invoice_number=INV-001 vendor=ABC GmbH

production    {"timestamp":"2026-09-05T13:47:55+0330","level":"INFO",
               "logger":"app.services.invoice_service","event":"invoice_created",
               "invoice_id":1,"invoice_number":"INV-001","vendor":"ABC GmbH"}
```

`LOG_LEVEL` filters: at `WARNING` the three `INFO` events disappear and `unexpected_error`
still gets through.

### What is never logged

Credentials, secrets, and full file contents. `DATABASE_URL` contains a password and is read
at startup, so this is checked rather than assumed — no password, and no connection string,
appears in any log line.

The same rule applies in the other direction. When an unexpected error occurs the traceback
goes to the log and the client gets a fixed string:

```json
{"detail": "Internal server error"}
```

An exception message can name a table, a column, or a connection string. Whoever is debugging
has the log; whoever sent the request does not need it.

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

## Docker

The whole application — API, database, and schema — runs with one command, no local Python,
`uv`, or PostgreSQL install required:

```bash
docker compose up
```

### What that starts

| Service | Image | Does |
| --- | --- | --- |
| `db` | `postgres:16` | The database. Data lives in a named volume, `pgdata`, not in the container. |
| `migrate` | built from this repo's `Dockerfile` | Runs `alembic upgrade head` once, then exits. |
| `app` | built from this repo's `Dockerfile` | Serves the API on `localhost:8000` once `migrate` finishes. |

`migrate` is a separate service rather than something `app` does for itself on startup. This
project has never let the application create its own tables — [Migrations](#migrations)
above builds the schema explicitly, on purpose, so a schema change is always a reviewed
migration file rather than a side effect of starting the process. Compose keeps that true:
migrating is its own named step, visible in `docker compose ps` and `docker compose logs
migrate`, not folded silently into `app`'s boot. `app` simply waits for it
(`depends_on: condition: service_completed_successfully`), and running it again on an
up-to-date schema is harmless — `alembic upgrade head` has nothing left to apply.

`db`'s healthcheck (`pg_isready`) is what makes that wait meaningful in the first place:
without it, Compose only knows the *container* has started, not that PostgreSQL inside it is
actually accepting connections yet — a race that would otherwise show up as `migrate` failing
intermittently on a cold start.

### Verify

Same checks as [Verify](#verify) above, against the containerized app:

| URL | Expected |
| --- | --- |
| <http://127.0.0.1:8000/> | `{"message":"InvoiceFlow API"}` |
| <http://127.0.0.1:8000/docs> | Interactive Swagger UI |

### The database port is 5433, not 5432

`db` is reachable from the host at `localhost:5433`, deliberately not `5432` — this project's
own [Database](#database) section above has a developer install a *native* PostgreSQL on
`5432` with these same `invoiceflow`/`invoiceflow` credentials. Both can run at once:

```bash
psql "postgresql://invoiceflow:invoiceflow@localhost:5433/invoiceflow" -c "select 1"
```

`app` and `migrate` never use this host port — inside the Compose network they reach `db` at
its service name, `db:5432`, which the host mapping does not affect either way.

### Data persistence

The point of `pgdata` as a named volume rather than an anonymous one is that it survives the
containers being recreated:

```bash
docker compose down      # stops and removes the containers; the volume is untouched
docker compose up -d     # the same data is still there
```

To actually clear it — for a genuinely fresh database, the same situation `TRUNCATE` or
`DROP SCHEMA` handle locally in [Resetting during development](#resetting-during-development) —
remove the volume explicitly:

```bash
docker compose down -v   # this time, gone
```

### Running it on a server

`docker-compose.lightsail.yml` is a small override for running this same stack on a long-lived
public machine rather than a laptop: restart policies so it survives a reboot, and the database
port bound to `127.0.0.1` so it is not published to the world.

```bash
docker compose -f docker-compose.yml -f docker-compose.lightsail.yml up -d
```

It is named for the exercise that produced it — [deploying to AWS
Lightsail](docs/deployment-lightsail.md), which covers the machine setup, the ports, the
database strategy, and the two false alarms that cost the most time along the way. That
instance no longer exists; the document is the record.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Service banner |
| `POST` | `/invoices` | Create an invoice |
| `GET` | `/invoices` | List all invoices |
| `GET` | `/invoices/{invoice_id}` | Fetch one invoice by ID |

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
| `items` | array | Line items with their derived amounts; `[]` for a header-only invoice |

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

### Line items

An invoice may carry line items. It does not have to — a header-only invoice is still valid,
and asserts its own totals. But once it says what was bought, the header has to agree with
the lines.

Per item:

| Rule | Issue code |
| --- | --- |
| `quantity > 0` | `INVALID_QUANTITY` |
| `unit_price >= 0` | `NEGATIVE_AMOUNT` |
| `0 <= tax_rate <= 100` | `INVALID_TAX_RATE` |

Then, across the invoice:

| Rule | Issue code |
| --- | --- |
| `sum(line_subtotal) == subtotal` | `LINE_TOTAL_MISMATCH` |
| `sum(line_tax) == tax` | `TAX_MISMATCH` |
| `sum(line_total) == total` | `LINE_TOTAL_MISMATCH` |

Item issues name the offending line: `"field": "items[1].quantity"`.

**The line amounts are derived, not sent.** A client supplies `description`, `quantity`,
`unit_price` and `tax_rate`; the server computes the rest. Sending `line_subtotal` does
nothing — it is a server-assigned field, like `id`.

```text
line_subtotal = quantity x unit_price
line_tax      = line_subtotal x tax_rate / 100
line_total    = line_subtotal + line_tax
```

`tax_rate` is a percentage: **19 means 19%**, not 1900%. (The playbook writes the tax rule
without the `/ 100`, which cannot be meant literally given its own `0 <= tax_rate <= 100`
bound.)

Each amount is rounded to cents **as it is computed**, not at the end:

```text
3 x 9.99      = 29.97
19% of 29.97  = 5.6943  ->  5.69
line_total    = 35.66
```

That is what makes the totals checkable against the lines — the numbers stored are the numbers
summed. Rounding only at the end would leave an invoice whose own lines do not add up to it.

### Duplicates are separate

`vendor + invoice_number` must be unique, but that is not checked alongside the rules above.
It is asked only of an invoice that already passes all of them, and it answers with **`409
Conflict`**, not `422`:

```json
{"detail":[{"code":"DUPLICATE_INVOICE","field":"invoice_number","message":"..."}]}
```

The ordering is deliberate. A duplicate of a *malformed* invoice is not a conflict — the data
is simply wrong — so `422` wins and the duplicate is never reported. Fix the data, resubmit,
and then the `409` is the accurate answer.

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

Both mean "well-formed JSON the server will not process." They were left distinguishable
rather than unified: the schema shape is FastAPI's own and changing it would mean overriding
its validation handler, which buys less than it costs.

An amount larger than the `invoices` table can store also lands here, as
`AMOUNT_OUT_OF_RANGE`. That one comes from the database driver rather than from a business
rule, and is translated in `app/core/error_handlers.py` — before this phase it escaped as a
bare `500` with the cause visible only in the server log.

### Status codes

| Code | When |
| --- | --- |
| `201 Created` | Invoice created |
| `200 OK` | Invoice or list returned |
| `404 Not Found` | No invoice with that ID |
| `409 Conflict` | An invoice with that vendor and number already exists |
| `422 Unprocessable Entity` | Request failed schema or business validation |

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
| Nothing ever modifies an invoice, so `updated_at` always equals `created_at` | — | Phase 39 — review workflow |
| An upload is read into memory whole, with no size limit | `POST /imports` a very large file | Phase 45 — security hardening |
| The uploaded file is not kept. Phases 18–21 process it in the same request, so there is nothing to re-read if processing fails | — | Phase 31 — S3 storage |
| A genuinely unexpected exception during `_process()` (anything other than the `InvoiceValidationError`, `DuplicateInvoiceError`, and `DataError` Phase 22 handles) still propagates past `save_with_errors()`, leaving the `ImportJob` stuck at `status="UPLOADED"` forever with every count at 0 and no record of what went wrong | — | unowned — needs an `error_message` column and a `FAILED` status transition wrapping the whole method |
| The template's currency list is **hardcoded prose** (`"EUR, USD or GBP"`) duplicating `SUPPORTED_CURRENCIES`. Adding a currency would make the template say something false | add a currency to the service; the template does not change | unowned |
| The template's worked example is not checked against the validator, so an edit could ship an example the API would reject | change a number in `_EXAMPLE_ROWS`; nothing fails | unowned |

The last two were found while reviewing Phase 16 and deliberately left. They are the same
class of problem that phase claimed to solve — a second source of truth that nothing keeps
honest — which is worth recording rather than quietly forgetting.

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
│   ├── dependencies.py      # get_db -> repository -> service
│   ├── core/
│   │   ├── config.py        # Settings — the only reader of the environment
│   │   ├── logging.py       # Formatters + configure_logging()
│   │   ├── exceptions.py    # Domain errors; no status codes
│   │   └── error_handlers.py # The only place mapping errors -> HTTP
│   ├── db/
│   │   ├── base.py          # Base — the declarative registry
│   │   └── session.py       # DATABASE_URL, engine, SessionLocal
│   ├── models/
│   │   ├── invoice.py       # Invoice, InvoiceItem
│   │   └── import_job.py    # ImportJob, ImportError
│   ├── repositories/
│   │   ├── invoice_repository.py       # All invoice SQL lives here
│   │   └── import_job_repository.py    # All import-job SQL lives here
│   ├── routers/
│   │   ├── imports.py       # Upload, report, and error-report endpoints
│   │   ├── invoices.py      # HTTP only: routes, status codes
│   │   └── templates.py     # The import template download
│   ├── schemas/
│   │   ├── invoice.py       # InvoiceCreate, InvoiceRead
│   │   └── import_job.py    # ImportJobRead, ImportErrorRead, ImportErrorList
│   └── services/
│       ├── invoice_service.py      # Business rules and invoice creation
│       ├── import_service.py       # Structural validation of uploads
│       ├── excel_parser.py         # Cells -> typed rows, or row errors
│       ├── excel_grouper.py        # Rows -> invoices, or invoice errors
│       └── excel_template.py       # The import contract, and the .xlsx builder
├── migrations/
│   ├── env.py               # Alembic config; reads DATABASE_URL
│   └── versions/            # One file per schema change
├── alembic.ini
├── Dockerfile
├── .dockerignore
├── docker-compose.yml
├── docker-compose.lightsail.yml  # Overrides for running on a public server
├── deploy/
│   └── lightsail-bootstrap.sh    # Cloud-init launch script for the VM
├── tests/
│   ├── conftest.py          # Rolled-back session, client, factories
│   ├── test_validation.py   # Unit — pure rules, no database
│   ├── test_service.py      # Service — rules plus duplicates
│   ├── test_repository.py   # Integration — real SQL
│   ├── test_api.py          # API — TestClient, status codes
│   ├── test_items.py        # Line items — rules, derivation, storage
│   ├── test_template.py     # The import contract
│   ├── test_imports.py      # Upload and structural validation
│   ├── test_parser.py       # Cells -> typed rows
│   ├── test_grouper.py      # Rows -> invoices
│   ├── test_import_report.py # The full import pipeline
│   ├── test_import_errors.py # The error report, pagination
│   ├── test_architecture.py # The layering rules, as assertions
│   ├── test_concurrency.py  # The duplicate race (xfail)
│   └── test_transaction_boundaries.py # Atomicity, one bad invoice vs the rest
├── pytest.ini
├── .env.example             # Every setting, with dev defaults
├── requirements.txt         # Pinned dependencies
├── docs/
│   ├── learning-log.md
│   └── deployment-lightsail.md   # The Lightsail exercise, and what it proved
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

### Wiring

Routes do not build their collaborators. They declare what they need and FastAPI supplies it,
resolving a chain defined once in [app/dependencies.py](app/dependencies.py):

```text
get_db()                  opens one session per request, closes it after the response
  -> get_invoice_repository(session)
       -> get_invoice_service(repository)
```

```python
@router.get("", response_model=list[InvoiceRead])
def list_invoices(repository: InvoiceRepositoryDep):
    return repository.list_all()
```

`app/routers/invoices.py` imports neither `InvoiceService`, `InvoiceRepository` nor
`SessionLocal` — it no longer needs to know those classes exist.

Two things this buys. Overriding one dependency redirects everything below it, so a test can
swap `get_db` for a test database without touching a route:

```python
app.dependency_overrides[get_invoice_service] = lambda: StubService()
```

And because the dependencies are declared with `Annotated` rather than as default values, the
route functions stay ordinary callables:

```python
create_invoice(invoice=data, service=StubService())   # no app, no server, no database
```
