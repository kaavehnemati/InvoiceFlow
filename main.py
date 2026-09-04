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


SUPPORTED_CURRENCIES = {"EUR", "USD", "GBP"}


def validate_invoice(invoice: InvoiceCreate) -> list[dict]:
    """Check an invoice against the business rules.

    InvoiceCreate already guarantees the invoice has the right *shape*. These
    rules decide whether it makes sense: an invoice whose fields are all the
    correct type can still claim that 1000 + 190 = 1300.

    Returns one issue per broken rule, or an empty list if the invoice is
    valid. Every rule is checked rather than stopping at the first failure, so
    a client learns everything that is wrong in a single response.

    This function deliberately knows nothing about HTTP. It returns data and
    lets the caller decide what that means, which is what will let the Excel
    importer in Phase 20 reuse it without having a request to fail.
    """
    issues = []

    for field in ("subtotal", "tax", "total"):
        if getattr(invoice, field) < 0:
            issues.append(
                {
                    "code": "NEGATIVE_AMOUNT",
                    "field": field,
                    "message": f"{field} must not be negative",
                }
            )

    if invoice.subtotal + invoice.tax != invoice.total:
        issues.append(
            {
                "code": "TOTAL_MISMATCH",
                "field": "total",
                "message": (
                    f"subtotal ({invoice.subtotal}) + tax ({invoice.tax}) "
                    f"must equal total ({invoice.total})"
                ),
            }
        )

    today = datetime.now(timezone.utc).date()
    if invoice.invoice_date > today:
        issues.append(
            {
                "code": "FUTURE_INVOICE_DATE",
                "field": "invoice_date",
                "message": f"invoice_date {invoice.invoice_date} is in the future",
            }
        )

    if invoice.currency not in SUPPORTED_CURRENCIES:
        issues.append(
            {
                "code": "INVALID_CURRENCY",
                "field": "currency",
                "message": (
                    f"currency must be one of "
                    f"{', '.join(sorted(SUPPORTED_CURRENCIES))}"
                ),
            }
        )

    return issues


@app.get("/")
def read_root():
    return {"message": "InvoiceFlow API"}


@app.post("/invoices", response_model=InvoiceRead, status_code=201)
def create_invoice(invoice: InvoiceCreate):
    global next_id

    issues = validate_invoice(invoice)
    if issues:
        raise HTTPException(status_code=422, detail=issues)

    stored = {
        "id": next_id,
        **invoice.model_dump(),
        "status": "VALID",
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
