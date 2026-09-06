from fastapi import APIRouter, Query, UploadFile

from app.core.exceptions import ImportJobNotFoundError
from app.dependencies import ImportJobRepositoryDep, ImportServiceDep
from app.schemas.import_job import ImportErrorList, ImportJobRead

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


@router.get("/{import_id}/errors", response_model=ImportErrorList)
def get_import_errors(
    import_id: str,
    repository: ImportJobRepositoryDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ImportErrorList:
    """Actionable detail behind the counts: what needs fixing, and where.

    404 only when the import itself does not exist. An import with zero
    errors is not an error condition -- it returns 200 with an empty list.
    """
    if repository.get_by_id(import_id) is None:
        raise ImportJobNotFoundError(import_id)

    errors, total = repository.list_errors(import_id, limit, offset)
    return ImportErrorList(total=total, limit=limit, offset=offset, errors=errors)
