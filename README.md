# InvoiceFlow

A backend platform for ingesting, validating, processing, and tracking invoices.

**Current status:** Phase 1 — in-memory invoice API. Invoices are created and read through
HTTP, but they are held in a plain Python list inside the server process. There is no
database, no field validation, and no architecture layers yet. Each is introduced by a later
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

Create an invoice:

```bash
curl -X POST http://127.0.0.1:8000/invoices \
  -H 'Content-Type: application/json' \
  -d '{"invoice_number":"INV-001","vendor":"ABC GmbH","subtotal":1000,"tax":190,"total":1190}'
```

```json
{"id":1,"invoice_number":"INV-001","vendor":"ABC GmbH","subtotal":1000,"tax":190,"total":1190}
```

The server assigns the `id`. List them, then fetch one:

```bash
curl http://127.0.0.1:8000/invoices
curl http://127.0.0.1:8000/invoices/1
```

## Known limitations

Every item below is a deliberate consequence of the current phase, not an oversight. The
playbook introduces each fix only once the problem is visible.

| Limitation | Try it | Resolved by |
| --- | --- | --- |
| Restarting the server erases every invoice, and IDs restart at 1 | create an invoice, restart, then `GET /invoices` → `[]` | Phase 6 — PostgreSQL |
| Any JSON is accepted; no field is required, typed, or checked | `POST /invoices -d '{"nonsense":true}'` succeeds | Phase 2 — Pydantic |
| A missing invoice returns `200 null` instead of `404` | `GET /invoices/999` → `null` | Phase 3 — HTTP semantics |
| Creating returns `200`, not `201 Created` | `curl -i -X POST /invoices` | Phase 3 — HTTP semantics |

One thing *is* already validated: `invoice_id` is annotated `int`, so `GET /invoices/abc`
returns `422` automatically. FastAPI enforces exactly what it has been told the shape of —
which is the argument for describing request bodies too, in Phase 2.

## Project layout

```text
.
├── main.py            # The entire application, for now
├── requirements.txt   # Pinned dependencies
├── docs/
│   └── learning-log.md
└── InvoiceFlow_Claude_Code_Implementation_Playbook.md
```
