# InvoiceFlow

A backend platform for ingesting, validating, processing, and tracking invoices.

**Current status:** Phase 2 — Pydantic request models. Invoice submissions are validated
against a declared schema, but the invoices themselves are still held in a plain Python list
inside the server process. There is no database, no business validation, and no architecture
layers yet. Each is introduced by a later
phase of [the implementation playbook](InvoiceFlow_Claude_Code_Implementation_Playbook.md),
and only once the previous phase makes the need for it obvious.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for environment and dependency management

> The system Python on this machine ships without `pip` and without `ensurepip`, so
> `python3 -m venv` cannot bootstrap itself. `uv` handles both the virtual environment and
> the installs without needing `sudo`.

## Setup

```bash
uv venv
uv pip install -r requirements.txt
```

## Run

```bash
uv run uvicorn main:app --reload
```

`main:app` means: import the module `main`, then serve the object named `app` inside it.
`--reload` restarts the server whenever a source file changes, which is convenient in
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

### Request schema

`POST /invoices` requires all seven fields. Anything missing or of the wrong type is
rejected with `422` before the handler runs.

| Field | Type |
| --- | --- |
| `invoice_number` | string |
| `vendor` | string |
| `invoice_date` | date, `YYYY-MM-DD` |
| `currency` | string |
| `subtotal`, `tax`, `total` | decimal |

### Examples

Create an invoice:

```bash
curl -X POST http://127.0.0.1:8000/invoices \
  -H 'Content-Type: application/json' \
  -d '{"invoice_number":"INV-001","vendor":"ABC GmbH","invoice_date":"2026-09-04",
       "currency":"EUR","subtotal":1000.00,"tax":190.00,"total":1190.00}'
```

```json
{"id":1,"invoice_number":"INV-001","vendor":"ABC GmbH","invoice_date":"2026-09-04","currency":"EUR","subtotal":1000.0,"tax":190.0,"total":1190.0}
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

## Known limitations

Every item below is a deliberate consequence of the current phase, not an oversight. The
playbook introduces each fix only once the problem is visible.

| Limitation | Try it | Resolved by |
| --- | --- | --- |
| Restarting the server erases every invoice, and IDs restart at 1 | create an invoice, restart, then `GET /invoices` → `[]` | Phase 6 — PostgreSQL |
| Fields are type-checked but not *sensible*: totals need not add up, dates may be in the future, and any currency string is accepted | `POST` with `subtotal:1000, tax:190, total:9999, currency:"XYZ", invoice_date:"2099-12-31"` → `200` | Phase 4 — business validation |
| A missing invoice returns `200 null` instead of `404` | `GET /invoices/999` → `null` | Phase 3 — HTTP semantics |
| Creating returns `200`, not `201 Created` | `curl -i -X POST /invoices` | Phase 3 — HTTP semantics |

Two things worth knowing about the current validation:

- **Amounts come back as JSON numbers.** They are `Decimal` inside the application, but JSON
  has no decimal type, so `1000.00` is serialized as `1000.0`. Precision is kept where the
  arithmetic happens and negotiated at the boundary.
- **Unknown fields are ignored, not rejected.** `{"...": ..., "nonsense": true}` succeeds and
  `nonsense` is simply dropped. This is Pydantic's default; a typo like `vendour` therefore
  surfaces as *"vendor: Field required"* rather than as a complaint about `vendour`.

## Project layout

```text
.
├── main.py            # The entire application, for now
├── requirements.txt   # Pinned dependencies
├── docs/
│   └── learning-log.md
└── InvoiceFlow_Claude_Code_Implementation_Playbook.md
```
