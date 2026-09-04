# InvoiceFlow

A backend platform for ingesting, validating, processing, and tracking invoices.

**Current status:** Phase 3 — response models and HTTP semantics. Requests and responses are
now two separately declared contracts, and status codes are meaningful. The invoices
themselves are still held in a plain Python list inside the server process. There is no
database, no business validation, and no architecture layers yet. Each is introduced by a
later
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
| `status` | string | Always `DRAFT` until Phase 4 |
| `created_at` | datetime | UTC |

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
| Restarting the server erases every invoice, and IDs restart at 1 | create an invoice, restart, then `GET /invoices` → `[]` | Phase 6 — PostgreSQL |
| Fields are type-checked but not *sensible*: totals need not add up, dates may be in the future, and any currency string is accepted. Every invoice is therefore stuck in `DRAFT` | `POST` with `subtotal:"1000", tax:"190", total:"9999", currency:"XYZ", invoice_date:"2099-12-31"` → `201 DRAFT` | Phase 4 — business validation |

One thing worth knowing about the current validation: **unknown fields are ignored, not
rejected.** `{"...": ..., "nonsense": true}` succeeds and `nonsense` is simply dropped. This
is Pydantic's default; a typo like `vendour` therefore surfaces as *"vendor: Field
required"* rather than as a complaint about `vendour`.

## Project layout

```text
.
├── main.py            # The entire application, for now
├── requirements.txt   # Pinned dependencies
├── docs/
│   └── learning-log.md
└── InvoiceFlow_Claude_Code_Implementation_Playbook.md
```
