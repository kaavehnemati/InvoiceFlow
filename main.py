from fastapi import FastAPI

app = FastAPI(title="InvoiceFlow API")

# Temporary storage. This list lives in the server process's memory, so every
# invoice is lost when the process restarts. Phase 6 replaces it with PostgreSQL.
invoices = []
next_id = 1


@app.get("/")
def read_root():
    return {"message": "InvoiceFlow API"}


@app.post("/invoices")
def create_invoice(invoice: dict):
    global next_id
    stored = {"id": next_id, **invoice}
    next_id += 1
    invoices.append(stored)
    return stored


@app.get("/invoices")
def list_invoices():
    return invoices


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int):
    for invoice in invoices:
        if invoice["id"] == invoice_id:
            return invoice
    return None
