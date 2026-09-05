from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError

from app.core.exceptions import (
    DuplicateInvoiceError,
    InvoiceNotFoundError,
    InvoiceValidationError,
)


def register_exception_handlers(app: FastAPI) -> None:
    """Translate errors into HTTP responses.

    This is the only module in the application that knows both a domain error
    and a status code. The service raises meaning; this decides what meaning
    looks like over HTTP. Swap the transport and this file is the only thing
    that has to change.
    """

    @app.exception_handler(InvoiceNotFoundError)
    async def handle_invoice_not_found(
        request: Request, exc: InvoiceNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Invoice not found"})

    @app.exception_handler(DuplicateInvoiceError)
    async def handle_duplicate_invoice(
        request: Request, exc: DuplicateInvoiceError
    ) -> JSONResponse:
        # 409 rather than 422: the request is well-formed and the invoice is
        # valid. It conflicts with state that already exists, which is a
        # different problem from being wrong.
        return JSONResponse(
            status_code=409,
            content={
                "detail": [
                    {
                        "code": "DUPLICATE_INVOICE",
                        "field": "invoice_number",
                        "message": str(exc),
                    }
                ]
            },
        )

    @app.exception_handler(InvoiceValidationError)
    async def handle_invoice_validation(
        request: Request, exc: InvoiceValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.issues})

    @app.exception_handler(DataError)
    async def handle_data_error(request: Request, exc: DataError) -> JSONResponse:
        # DataError comes from the driver, not from our code, so it gets no
        # domain exception -- nothing would ever raise it. It is handled here
        # because this module is already the boundary between infrastructure
        # and HTTP, which keeps SQLAlchemy out of the service and the router.
        #
        # In practice this means an amount the invoices table cannot hold.
        # Without this handler it escaped as a bare 500 with the cause visible
        # only in the server log.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {
                        "code": "AMOUNT_OUT_OF_RANGE",
                        "field": None,
                        "message": (
                            "an amount is outside the range this system can store"
                        ),
                    }
                ]
            },
        )
