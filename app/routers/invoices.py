from fastapi import APIRouter, HTTPException

from app.db.session import SessionLocal
from app.repositories.invoice_repository import InvoiceRepository
from app.schemas.invoice import InvoiceCreate, InvoiceRead
from app.services.invoice_service import InvoiceService

router = APIRouter(prefix="/invoices", tags=["invoices"])


# The route paths are "" rather than "/". Under the router's "/invoices" prefix
# an empty path produces exactly /invoices, while "/" would produce /invoices/
# and make the old URL a redirect.
#
# These routes still open the session and construct their collaborators by hand.
# Phase 10 replaces both with injected dependencies.
@router.post("", response_model=InvoiceRead, status_code=201)
def create_invoice(invoice: InvoiceCreate):
    with SessionLocal() as session:
        service = InvoiceService(InvoiceRepository(session))
        created, issues = service.create(invoice)
        # The service reports what is wrong; deciding that "wrong" means 422 is
        # this layer's job, and the only thing this layer decides.
        if issues:
            raise HTTPException(status_code=422, detail=issues)
        return created


# Reads go straight to the repository. There is no business behavior to add, so
# routing them through the service would be pure passthrough.
@router.get("", response_model=list[InvoiceRead])
def list_invoices():
    with SessionLocal() as session:
        return InvoiceRepository(session).list_all()


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: int):
    with SessionLocal() as session:
        invoice = InvoiceRepository(session).get_by_id(invoice_id)
        if invoice is None:
            raise HTTPException(status_code=404, detail="Invoice not found")
        return invoice
