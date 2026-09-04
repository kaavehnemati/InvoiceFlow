from fastapi import FastAPI

app = FastAPI(title="InvoiceFlow API")


@app.get("/")
def read_root():
    return {"message": "InvoiceFlow API"}
