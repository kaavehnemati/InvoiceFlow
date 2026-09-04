from datetime import date
from decimal import Decimal

from fastapi import FastAPI
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


@app.get("/")
def read_root():
    return {"message": "InvoiceFlow API"}


@app.post("/invoices")
def create_invoice(invoice: InvoiceCreate):
    global next_id
    stored = {"id": next_id, **invoice.model_dump()}
    next_id += 1
    invoices.append(stored)
    return stored


@app.get("/invoices")
def list_invoices():
    return invoices


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int):
    for invoice in invoices:
        if invoice["id"] == invoice_id:
            return invoice
    return None
