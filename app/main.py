from fastapi import FastAPI

from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.routers import invoices

# First, so nothing gets a chance to log through an unconfigured root logger.
configure_logging()

app = FastAPI(title="InvoiceFlow API")

register_exception_handlers(app)
app.include_router(invoices.router)


@app.get("/")
def read_root():
    return {"message": "InvoiceFlow API"}
