from fastapi import FastAPI

from app.db.base import Base
from app.db.session import engine
from app.models import invoice as invoice_model  # noqa: F401
from app.routers import invoices

app = FastAPI(title="InvoiceFlow API")

# Importing the model above looks unused, and is not: it is what registers the
# invoices table on Base.metadata, so create_all() has something to create.
#
# create_all() only ever adds missing tables. It cannot alter an existing one,
# so changing a column here would silently do nothing. Phase 7 replaces this
# with Alembic migrations, which is the real answer.
Base.metadata.create_all(bind=engine)

app.include_router(invoices.router)


@app.get("/")
def read_root():
    return {"message": "InvoiceFlow API"}
