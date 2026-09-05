from typing import Annotated, Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.import_job_repository import ImportJobRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.services.import_service import ImportService
from app.services.invoice_service import InvoiceService


def get_db() -> Iterator[Session]:
    """Provide a database session for the duration of one request.

    FastAPI runs this generator up to the yield, hands the session to whatever
    asked for it, and resumes it once the response has been sent -- so the with
    block closes the session exactly once per request, even if the route raised.

    Note that the session now outlives the route function: it is still open
    while the response is serialized. Before this phase each route closed its
    own session before returning, and serialization happened against a detached
    object.
    """
    with SessionLocal() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


def get_invoice_repository(session: DbSession) -> InvoiceRepository:
    return InvoiceRepository(session)


InvoiceRepositoryDep = Annotated[InvoiceRepository, Depends(get_invoice_repository)]


def get_invoice_service(repository: InvoiceRepositoryDep) -> InvoiceService:
    return InvoiceService(repository)


InvoiceServiceDep = Annotated[InvoiceService, Depends(get_invoice_service)]


def get_import_job_repository(session: DbSession) -> ImportJobRepository:
    return ImportJobRepository(session)


ImportJobRepositoryDep = Annotated[
    ImportJobRepository, Depends(get_import_job_repository)
]


def get_import_service(
    repository: ImportJobRepositoryDep, invoice_service: InvoiceServiceDep
) -> ImportService:
    return ImportService(repository, invoice_service)


ImportServiceDep = Annotated[ImportService, Depends(get_import_service)]

# Each provider asks for the one above it rather than building it, so FastAPI
# resolves the whole chain -- session -> repository -> service -- and every
# layer in a single request shares one session. Overriding get_db therefore
# redirects everything below it, which is how Phase 14's tests will swap in a
# test database without touching a single route.
