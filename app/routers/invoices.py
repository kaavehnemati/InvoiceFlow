from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.invoice import Invoice
from app.schemas.invoice import InvoiceCreate, InvoiceRead

router = APIRouter(prefix="/invoices", tags=["invoices"])

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
    importer in Phase 20 reuse it without having a request to fail. Phase 9
    moves it out of this router and into a service layer for the same reason.
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


# The route paths are "" rather than "/". Under the router's "/invoices" prefix
# an empty path produces exactly /invoices, while "/" would produce /invoices/
# and make the old URL a redirect.
#
# These routes open a database session directly. That is what the playbook asks
# for at this phase; Phase 8 moves the queries into a repository and Phase 10
# replaces SessionLocal() with an injected dependency.
@router.post("", response_model=InvoiceRead, status_code=201)
def create_invoice(invoice: InvoiceCreate):
    issues = validate_invoice(invoice)
    if issues:
        raise HTTPException(status_code=422, detail=issues)

    with SessionLocal() as session:
        now = datetime.now(timezone.utc)
        db_invoice = Invoice(
            **invoice.model_dump(),
            status="VALID",
            created_at=now,
            # An invoice that has never been modified was last changed when it
            # was created. The model's onupdate takes over from here.
            updated_at=now,
        )
        session.add(db_invoice)
        session.commit()
        # commit() expires the instance, so its attributes are unloaded. The id
        # was assigned by the database and has never been in Python at all.
        # refresh() re-reads the row to bring both back.
        session.refresh(db_invoice)
        return db_invoice


@router.get("", response_model=list[InvoiceRead])
def list_invoices():
    with SessionLocal() as session:
        # A table has no inherent row order. The in-memory list happened to
        # return insertion order, so ordering by id preserves that behavior.
        return session.scalars(select(Invoice).order_by(Invoice.id)).all()


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: int):
    with SessionLocal() as session:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            raise HTTPException(status_code=404, detail="Invoice not found")
        return invoice
