# InvoiceFlow

A backend platform for ingesting, validating, processing, and tracking invoices.

**Current status:** Phase 0 — bootstrap. The application is a single FastAPI route. There is
no database, no validation, and no architecture layers yet. Each is introduced by a later
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

Or from the command line:

```bash
curl -i http://127.0.0.1:8000/
```

## Project layout

```text
.
├── main.py            # The entire application, for now
├── requirements.txt   # Pinned dependencies
├── docs/
│   └── learning-log.md
└── InvoiceFlow_Claude_Code_Implementation_Playbook.md
```
