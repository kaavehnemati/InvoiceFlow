import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Read from the environment so a real deployment never depends on a value
# committed to source. The fallback is a local development credential, not a
# secret. Phase 11 replaces this with a proper settings object and .env.example.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://invoiceflow:invoiceflow@localhost:5432/invoiceflow",
)

# The engine owns the connection pool. One per process; it does not connect
# until something actually runs a statement.
engine = create_engine(DATABASE_URL)

# A factory, not a session. Call SessionLocal() to start a new unit of work.
SessionLocal = sessionmaker(bind=engine, autoflush=False)
