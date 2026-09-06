"""Transaction boundaries: what must succeed or fail together, and what must not.

Two claims, verified rather than assumed -- the second one turned out to be
false before this phase, and these tests are what proved it.
"""
from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy.exc import DataError

from app.models.import_job import ImportJob
from app.models.invoice import Invoice, InvoiceItem
from app.schemas.invoice import InvoiceCreate, InvoiceItemCreate
from app.services.excel_template import SHEET_NAME, build_template_workbook


def workbook_with(*rows) -> bytes:
    wb = load_workbook(BytesIO(build_template_workbook()))
    for row in rows:
        wb[SHEET_NAME].append(list(row))
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def upload(client, content: bytes, filename="invoices.xlsx"):
    return client.post(
        "/imports",
        files={"file": (filename, content, "application/vnd.openxmlformats-"
                        "officedocument.spreadsheetml.sheet")},
    )


# ================================================ invoice + items atomicity


def test_a_failed_item_insert_leaves_no_invoice_behind(service, db_session):
    """The Definition of Done, direct: "a failed item insert cannot leave a
    half-created invoice."

    unit_price alone overflows NUMERIC(12,2) here, with quantity small enough
    that the derived line (and therefore the header totals) stay in range --
    isolating the failure to the item's own column, not the header's. This is
    the exact reproduction that motivated this phase.
    """
    data = InvoiceCreate(
        invoice_number="ATOMIC-1", vendor="V", invoice_date=date(2026, 1, 15),
        currency="EUR", subtotal=Decimal("100000000.00"), tax=Decimal("0.00"),
        total=Decimal("100000000.00"),
        items=[
            InvoiceItemCreate(
                description="huge unit price, tiny qty",
                quantity=Decimal("0.001"),
                unit_price=Decimal("99999999999.00"),  # overflows the item column
                tax_rate=Decimal("0"),
            )
        ],
    )

    try:
        service.create(data)
        assert False, "expected a DataError from the database"
    except DataError:
        # The session is unusable again until this runs -- querying it first
        # would raise PendingRollbackError instead of answering the question.
        # (An early draft of this exact test proved that the hard way.)
        db_session.rollback()

    assert db_session.query(Invoice).filter_by(invoice_number="ATOMIC-1").count() == 0
    assert db_session.query(InvoiceItem).count() == 0


def test_session_recovers_after_a_rolled_back_failure(service, repository, db_session):
    """The mechanism this phase's fix depends on, isolated.

    A failed commit leaves the session unusable until it is explicitly rolled
    back. Verified directly: without the rollback, the next create() call on
    the same session would also fail.
    """
    bad = InvoiceCreate(
        invoice_number="ROLLBACK-BAD", vendor="V", invoice_date=date(2026, 1, 15),
        currency="EUR", subtotal=Decimal("100000000.00"), tax=Decimal("0"),
        total=Decimal("100000000.00"),
        items=[InvoiceItemCreate(description="x", quantity=Decimal("0.001"),
                                  unit_price=Decimal("99999999999.00"),
                                  tax_rate=Decimal("0"))],
    )
    good = InvoiceCreate(
        invoice_number="ROLLBACK-GOOD", vendor="V", invoice_date=date(2026, 1, 15),
        currency="EUR", subtotal=Decimal("10.00"), tax=Decimal("1.90"),
        total=Decimal("11.90"),
    )

    try:
        service.create(bad)
    except DataError:
        db_session.rollback()

    result = service.create(good)
    assert result.invoice_number == "ROLLBACK-GOOD"
    assert result.status == "VALID"


# ============================================ one bad invoice, many others


def test_a_db_level_failure_does_not_abort_the_rest_of_the_import(client, db_session):
    """The defect this phase actually fixes.

    Before: INV-AFTER was never attempted, the ImportJob stayed at UPLOADED
    with every count at 0, no errors were recorded, and the client received a
    bare 422 for the whole upload instead of a completed report.
    """
    content = workbook_with(
        ["INV-BEFORE", "Acme Ltd", "2026-01-15", "Widgets",
         1, 10.00, 19, "EUR", 10.00, 1.90, 11.90],
        # unit_price alone overflows NUMERIC(12,2); the header stays in range
        ["INV-DBFAIL", "Acme Ltd", "2026-01-15", "Huge",
         "0.001", 99999999999.00, 0, "EUR", 100000000.00, 0, 100000000.00],
        ["INV-AFTER", "Acme Ltd", "2026-01-15", "Widgets",
         1, 10.00, 19, "EUR", 10.00, 1.90, 11.90],
    )

    response = upload(client, content)

    # not a bare 422 for the whole upload -- the file itself is fine
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "COMPLETED"

    stored = {i.invoice_number for i in db_session.query(Invoice).all()}
    assert stored == {"INV-BEFORE", "INV-AFTER"}
    assert db_session.query(ImportJob).filter_by(id=body["id"]).one().status == "COMPLETED"


def test_the_report_counts_reflect_the_db_level_failure(client):
    content = workbook_with(
        ["INV-BEFORE", "Acme Ltd", "2026-01-15", "Widgets",
         1, 10.00, 19, "EUR", 10.00, 1.90, 11.90],
        ["INV-DBFAIL", "Acme Ltd", "2026-01-15", "Huge",
         "0.001", 99999999999.00, 0, "EUR", 100000000.00, 0, 100000000.00],
        ["INV-AFTER", "Acme Ltd", "2026-01-15", "Widgets",
         1, 10.00, 19, "EUR", 10.00, 1.90, 11.90],
    )

    body = upload(client, content).json()

    assert body["invoices_found"] == 3
    assert body["invoices_created"] == 2
    assert body["invoices_failed"] == 1
    assert body["invoices_found"] == (
        body["invoices_created"] + body["invoices_failed"] + body["duplicate_invoices"]
    )


def test_the_db_level_failure_is_queryable_via_the_error_report(client):
    content = workbook_with(
        ["INV-DBFAIL", "Acme Ltd", "2026-01-15", "Huge",
         "0.001", 99999999999.00, 0, "EUR", 100000000.00, 0, 100000000.00],
    )

    import_id = upload(client, content).json()["id"]
    errors = client.get(f"/imports/{import_id}/errors").json()["errors"]

    assert len(errors) == 1
    error = errors[0]
    assert error["code"] == "AMOUNT_OUT_OF_RANGE"
    assert error["invoice_number"] == "INV-DBFAIL"
    # same code Phase 12 uses for the identical failure on a single JSON
    # request -- one failure, one meaning, regardless of how it arrived
    assert error["summary"].startswith("Invoice INV-DBFAIL → ")


# ============================================== the playbook's own guarantee


def test_a_business_rule_failure_does_not_cost_other_invoices(client, db_session):
    """Already true before this phase; made permanent rather than incidental."""
    content = workbook_with(
        ["INV-GOOD-1", "Acme Ltd", "2026-01-15", "Widgets",
         1, 10.00, 19, "EUR", 10.00, 1.90, 11.90],
        ["INV-BADRULE", "Acme Ltd", "2026-01-15", "Widgets",
         1, 10.00, 19, "XYZ", 10.00, 1.90, 11.90],  # unsupported currency
        ["INV-GOOD-2", "Acme Ltd", "2026-01-15", "Widgets",
         1, 10.00, 19, "EUR", 10.00, 1.90, 11.90],
    )

    upload(client, content)

    stored = {i.invoice_number for i in db_session.query(Invoice).all()}
    assert stored == {"INV-GOOD-1", "INV-GOOD-2"}


def test_a_duplicate_does_not_cost_other_invoices(client, db_session):
    client.post("/invoices", json={
        "invoice_number": "ALREADY-EXISTS", "vendor": "Acme Ltd",
        "invoice_date": "2026-01-15", "currency": "EUR",
        "subtotal": "10.00", "tax": "1.90", "total": "11.90",
    })

    content = workbook_with(
        ["INV-GOOD", "Acme Ltd", "2026-01-15", "Widgets",
         1, 10.00, 19, "EUR", 10.00, 1.90, 11.90],
        ["ALREADY-EXISTS", "Acme Ltd", "2026-01-15", "Widgets",
         1, 10.00, 19, "EUR", 10.00, 1.90, 11.90],
    )

    upload(client, content)

    stored = {i.invoice_number for i in db_session.query(Invoice).all()}
    assert stored == {"ALREADY-EXISTS", "INV-GOOD"}
    assert db_session.query(Invoice).filter_by(invoice_number="ALREADY-EXISTS").count() == 1
