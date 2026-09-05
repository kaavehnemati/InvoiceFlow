from fastapi import APIRouter, HTTPException

from app.dependencies import InvoiceRepositoryDep, InvoiceServiceDep
from app.schemas.invoice import InvoiceCreate, InvoiceRead

router = APIRouter(prefix="/invoices", tags=["invoices"])


# The route paths are "" rather than "/". Under the router's "/invoices" prefix
# an empty path produces exactly /invoices, while "/" would produce /invoices/
# and make the old URL a redirect.
#
# The routes no longer build anything. They declare what they need and FastAPI
# supplies it, which is why this module imports neither InvoiceService,
# InvoiceRepository nor SessionLocal -- it does not need to know they exist.
@router.post("", response_model=InvoiceRead, status_code=201)
def create_invoice(invoice: InvoiceCreate, service: InvoiceServiceDep):
    created, issues = service.create(invoice)
    # The service reports what is wrong; deciding that "wrong" means 422 is
    # this layer's job, and the only thing this layer decides.
    if issues:
        raise HTTPException(status_code=422, detail=issues)
    return created


# Reads go straight to the repository. There is no business behavior to add, so
# routing them through the service would be pure passthrough.
@router.get("", response_model=list[InvoiceRead])
def list_invoices(repository: InvoiceRepositoryDep):
    return repository.list_all()


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: int, repository: InvoiceRepositoryDep):
    invoice = repository.get_by_id(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice
