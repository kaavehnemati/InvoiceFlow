from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import engine
from app.dependencies import get_db
from app.main import app
from app.models.invoice import Invoice
from app.repositories.invoice_repository import InvoiceRepository
from app.schemas.invoice import InvoiceCreate
from app.services.invoice_service import InvoiceService


@pytest.fixture
def db_session():
    """A session whose work is thrown away when the test ends.

    The test runs inside a transaction on a single connection, and that
    transaction is rolled back afterwards. Nothing a test writes survives, so
    the suite can run against the development database without disturbing it.

    join_transaction_mode="create_savepoint" is what makes this work here.
    InvoiceRepository.create() calls session.commit(), and without it that
    commit would end the outer transaction and there would be nothing left to
    roll back. With it, the session's commits release savepoints instead, and
    the outer rollback still undoes everything.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    # Rolling back keeps a test's writes from persisting, but it does nothing
    # about rows that were already committed -- and the development database
    # has some. A test asserting "there is one invoice" would see those too.
    #
    # Deleting them here, inside the transaction, gives every test an empty
    # table to reason about; the rollback below puts them straight back.
    #
    # Every table, not a hand-maintained list. Phase 17 added import_jobs and
    # a test asserting it was empty, but not the matching cleanup, so that test
    # passed only while the database happened to be empty -- and failed the
    # first time anyone uploaded a file by hand. sorted_tables is dependency
    # ordered, so reversing it deletes children before parents.
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(delete(table))
    session.flush()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def repository(db_session):
    return InvoiceRepository(db_session)


@pytest.fixture
def service(repository):
    return InvoiceService(repository)


@pytest.fixture
def client(db_session):
    """A test client whose requests use the test's transaction.

    Overriding get_db is enough to redirect the whole chain, because
    get_invoice_repository and get_invoice_service both descend from it. This
    is the seam Phase 10 built, used for the first time.
    """
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


TODAY = date.today()

_DEFAULTS = {
    "invoice_number": "INV-001",
    "vendor": "ABC GmbH",
    "invoice_date": TODAY,
    "currency": "EUR",
    "subtotal": Decimal("1000.00"),
    "tax": Decimal("190.00"),
    "total": Decimal("1190.00"),
}


@pytest.fixture
def make_invoice():
    """Build a valid InvoiceCreate, overriding only what a test cares about."""

    def _make(**overrides) -> InvoiceCreate:
        return InvoiceCreate(**{**_DEFAULTS, **overrides})

    return _make


@pytest.fixture
def invoice_payload():
    """The same thing as a JSON-ready dict, for API tests."""

    def _payload(**overrides) -> dict:
        data = {**_DEFAULTS, **overrides}
        return {k: str(v) for k, v in data.items()}

    return _payload
