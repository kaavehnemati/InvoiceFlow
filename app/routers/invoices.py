from fastapi import APIRouter

from app.core.exceptions import InvoiceNotFoundError
from app.dependencies import InvoiceRepositoryDep, InvoiceServiceDep
from app.schemas.invoice import InvoiceCreate, InvoiceRead

router = APIRouter(prefix="/invoices", tags=["invoices"])


# The route paths are "" rather than "/". Under the router's "/invoices" prefix
# an empty path produces exactly /invoices, while "/" would produce /invoices/
# and make the old URL a redirect.
#
# These routes no longer decide what an error looks like. They raise domain
# errors and let app/core/error_handlers.py map them to status codes, which is
# why this module no longer imports HTTPException at all.
@router.post("", response_model=InvoiceRead, status_code=201)
def create_invoice(invoice: InvoiceCreate, service: InvoiceServiceDep):
    return service.create(invoice)


# Reads go straight to the repository. There is no business behavior to add, so
# routing them through the service would be pure passthrough.
@router.get("", response_model=list[InvoiceRead])
def list_invoices(repository: InvoiceRepositoryDep):
    return repository.list_all()


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: int, repository: InvoiceRepositoryDep):
    invoice = repository.get_by_id(invoice_id)
    if invoice is None:
        raise InvoiceNotFoundError(invoice_id)
    return invoice
