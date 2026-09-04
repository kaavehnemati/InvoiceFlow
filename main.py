from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="InvoiceFlow API")

# Temporary storage. This list lives in the server process's memory, so every
# invoice is lost when the process restarts. Phase 6 replaces it with PostgreSQL.
invoices = []
next_id = 1


class InvoiceCreate(BaseModel):
    """The shape of an invoice a client is allowed to send.

    This describes structure only: which fields are required and what type each
    one is. Whether the numbers make sense together is a separate question, and
    Phase 4 answers it.

    Amounts use Decimal rather than float because binary floats cannot represent
    values like 0.10 exactly, so their arithmetic drifts. On money that drift
    becomes a cent that does not reconcile.
    """

    invoice_number: str
    vendor: str
    invoice_date: date
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal


class InvoiceRead(BaseModel):
    """The shape of an invoice the API returns.

    Deliberately a separate class rather than a subclass of InvoiceCreate. The
    two describe opposite directions of travel and are free to diverge: a field
    the client sends need not be a field the API echoes back, and vice versa.
    `id`, `status` and `created_at` are assigned by the server, so a client can
    never supply them.
    """

    id: int
    invoice_number: str
    vendor: str
    invoice_date: date
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    status: str
    created_at: datetime


@app.get("/")
def read_root():
    return {"message": "InvoiceFlow API"}


@app.post("/invoices", response_model=InvoiceRead, status_code=201)
def create_invoice(invoice: InvoiceCreate):
    global next_id
    # Every invoice starts as DRAFT because nothing has checked it yet. Phase 4
    # adds the business rules that decide whether it becomes VALID or REJECTED.
    stored = {
        "id": next_id,
        **invoice.model_dump(),
        "status": "DRAFT",
        "created_at": datetime.now(timezone.utc),
    }
    next_id += 1
    invoices.append(stored)
    return stored


@app.get("/invoices", response_model=list[InvoiceRead])
def list_invoices():
    return invoices


@app.get("/invoices/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: int):
    for invoice in invoices:
        if invoice["id"] == invoice_id:
            return invoice
    raise HTTPException(status_code=404, detail="Invoice not found")
