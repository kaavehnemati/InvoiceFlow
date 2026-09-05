from fastapi import APIRouter, Response

from app.services.excel_template import (
    TEMPLATE_FILENAME,
    XLSX_MEDIA_TYPE,
    build_template_workbook,
)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get(
    "/invoice-import",
    # response_class is what stops FastAPI advertising application/json. The
    # responses= block below only *adds* a content type; without this the
    # documentation would list both, and a generated client would expect JSON.
    response_class=Response,
    responses={
        200: {
            "description": "The invoice import template as an .xlsx workbook.",
            "content": {XLSX_MEDIA_TYPE: {}},
        }
    },
)
def download_invoice_import_template() -> Response:
    """Download the standard invoice import template."""
    # A Response rather than a return value FastAPI serializes: there is no
    # JSON here, only bytes. Content-Disposition is what makes a browser save
    # it under a name instead of trying to render it.
    return Response(
        content=build_template_workbook(),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{TEMPLATE_FILENAME}"'
        },
    )
