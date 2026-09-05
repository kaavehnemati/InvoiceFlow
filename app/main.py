from fastapi import FastAPI

from app.core.error_handlers import register_exception_handlers
from app.routers import invoices

app = FastAPI(title="InvoiceFlow API")

register_exception_handlers(app)
app.include_router(invoices.router)


@app.get("/")
def read_root():
    return {"message": "InvoiceFlow API"}
