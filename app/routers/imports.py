from fastapi import APIRouter, UploadFile

from app.dependencies import ImportServiceDep
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
