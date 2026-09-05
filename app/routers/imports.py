from fastapi import APIRouter, UploadFile

from app.core.exceptions import ImportJobNotFoundError
from app.dependencies import ImportJobRepositoryDep, ImportServiceDep
from app.schemas.import_job import ImportJobRead

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("", response_model=ImportJobRead, status_code=201)
async def create_import(file: UploadFile, service: ImportServiceDep) -> ImportJobRead:
    """Upload an invoice import file.

    Checks the workbook's structure only. Whether the invoices inside it are
    any good is Phase 20's question -- a file full of invoices that will later
    be rejected is still a structurally valid file.
    """
    # async for a reason rather than habit: UploadFile.read() is awaitable, and
    # this is the first route in the project that needs it.
    return service.create_from_upload(file.filename, await file.read())


@router.get("/{import_id}", response_model=ImportJobRead)
def get_import(import_id: str, repository: ImportJobRepositoryDep) -> ImportJobRead:
    """The report for one import: what was read, and what became of it."""
    job = repository.get_by_id(import_id)
    if job is None:
        raise ImportJobNotFoundError(import_id)
    return job
