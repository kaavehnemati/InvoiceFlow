from fastapi import FastAPI

from app.routers import invoices

app = FastAPI(title="InvoiceFlow API")

app.include_router(invoices.router)


@app.get("/")
def read_root():
    return {"message": "InvoiceFlow API"}
