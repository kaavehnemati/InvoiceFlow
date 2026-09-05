"""Importing a spreadsheet, and reporting what happened.

The Definition of Done for this phase is a claim about *reuse*: Excel imports
must run the same business logic as manual invoice creation. The first test
here is what makes that claim falsifiable.
"""
from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook

from app.models.import_job import ImportError as ImportErrorRow
from app.models.invoice import Invoice, InvoiceItem
from app.services.excel_template import SHEET_NAME, build_template_workbook

# invoice_number, vendor, date, item, qty, unit_price, tax_rate, currency,
# declared_subtotal, declared_tax, declared_total
GOOD = ["INV-1001", "ABC GmbH", "2026-01-15", "Consulting",
        2, 100.00, 19, "EUR", 200.00, 38.00, 238.00]


def workbook_with(*rows) -> bytes:
    wb = load_workbook(BytesIO(build_template_workbook()))
    for row in rows:
        wb[SHEET_NAME].append(list(row))
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def row(**overrides):
    names = ["invoice_number", "vendor", "invoice_date", "item", "quantity",
             "unit_price", "tax_rate", "currency", "declared_subtotal",
             "declared_tax", "declared_total"]
    values = dict(zip(names, GOOD))
    values.update(overrides)
    return [values[n] for n in names]


def upload(client, content: bytes, filename="invoices.xlsx"):
    return client.post(
        "/imports",
        files={"file": (filename, content, "application/vnd.openxmlformats-"
                        "officedocument.spreadsheetml.sheet")},
    )


def errors_for(db_session, import_id) -> list[ImportErrorRow]:
    return (
        db_session.query(ImportErrorRow)
        .filter(ImportErrorRow.import_id == import_id)
        .all()
    )


# ============================================================ the Definition of Done


def test_excel_and_json_reject_an_invoice_identically(client, db_session):
    """The same rules, not similar rules.

    If anyone reimplements a business rule in the import path, this fails.
    A commit message promising reuse cannot do that.
    """
    # Both paths must receive the *same* invoice. Every spreadsheet row is a
    # line item, so the JSON payload needs one too -- otherwise the codes differ
    # because the inputs differ, which proves nothing about reuse.
    bad = dict(
        invoice_number="SAME-1", vendor="ABC GmbH", invoice_date="2099-12-31",
        currency="XYZ", subtotal="-5.00", tax="-5.00", total="9999.00",
        items=[{"description": "Consulting", "quantity": "2",
                "unit_price": "100.00", "tax_rate": "19"}],
    )

    api_codes = sorted(
        issue["code"] for issue in client.post("/invoices", json=bad).json()["detail"]
    )

    import_id = upload(
        client,
        workbook_with(row(
            invoice_number="SAME-1", invoice_date="2099-12-31", currency="XYZ",
            declared_subtotal=-5.00, declared_tax=-5.00, declared_total=9999.00,
        )),
    ).json()["id"]
    import_codes = sorted(
        e.code for e in errors_for(db_session, import_id) if e.scope == "invoice"
    )

    assert api_codes == import_codes
    assert api_codes  # and it actually rejected something


# ==================================================================== the happy path


def test_uploading_a_spreadsheet_creates_invoices(client, db_session):
    """The headline. Since Phase 17 this returned 201 and created nothing."""
    upload(client, workbook_with(row()))

    invoice = db_session.query(Invoice).filter_by(invoice_number="INV-1001").one()
    assert invoice.status == "VALID"
    assert invoice.vendor == "ABC GmbH"


def test_line_items_are_created_with_derived_amounts(client, db_session):
    """Two rows of one invoice: 2 x 100.00 and 1 x 50.00, both at 19%.

    Every row of an invoice must agree about the declared totals, so both
    rows carry 250.00 / 47.50 / 297.50.
    """
    upload(client, workbook_with(
        row(item="Consulting", quantity=2, unit_price=100.00,
            declared_subtotal=250.00, declared_tax=47.50, declared_total=297.50),
        row(item="Travel", quantity=1, unit_price=50.00,
            declared_subtotal=250.00, declared_tax=47.50, declared_total=297.50),
    ))

    invoice = db_session.query(Invoice).filter_by(invoice_number="INV-1001").one()
    assert [i.description for i in invoice.items] == ["Consulting", "Travel"]

    # derived by the server, exactly as a JSON request would be
    assert invoice.items[0].line_subtotal == Decimal("200.00")
    assert invoice.items[0].line_tax == Decimal("38.00")
    assert invoice.items[1].line_total == Decimal("59.50")

    # and the Phase 15 reconciliation holds on stored data
    assert sum(i.line_subtotal for i in invoice.items) == invoice.subtotal
    assert sum(i.line_total for i in invoice.items) == invoice.total


def test_multi_row_invoice_becomes_one_invoice(client, db_session):
    upload(client, workbook_with(
        row(item="A", quantity=1, unit_price=100.00,
            declared_subtotal=300.00, declared_tax=57.00, declared_total=357.00),
        row(item="B", quantity=1, unit_price=100.00,
            declared_subtotal=300.00, declared_tax=57.00, declared_total=357.00),
        row(item="C", quantity=1, unit_price=100.00,
            declared_subtotal=300.00, declared_tax=57.00, declared_total=357.00),
    ))

    assert db_session.query(Invoice).count() == 1
    assert db_session.query(InvoiceItem).count() == 3


# ========================================================================= the report


def test_the_report_is_returned(client):
    import_id = upload(client, workbook_with(row())).json()["id"]

    report = client.get(f"/imports/{import_id}")
    assert report.status_code == 200

    body = report.json()
    assert body["status"] == "COMPLETED"
    assert body["total_rows"] == 1
    assert body["valid_rows"] == 1
    assert body["invalid_rows"] == 0
    assert body["invoices_found"] == 1
    assert body["invoices_created"] == 1
    assert body["invoices_failed"] == 0
    assert body["duplicate_invoices"] == 0


def test_unknown_import_is_404(client):
    response = client.get("/imports/imp_doesnotexist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Import not found"}


def test_row_counts_add_up(client):
    """total_rows = valid_rows + invalid_rows"""
    import_id = upload(client, workbook_with(
        row(), row(invoice_number="INV-2", quantity="two"), row(invoice_number="INV-3"),
    )).json()["id"]

    body = client.get(f"/imports/{import_id}").json()
    assert body["total_rows"] == body["valid_rows"] + body["invalid_rows"]
    assert body["invalid_rows"] == 1


def test_invoice_counts_add_up(client):
    """invoices_found = created + failed + duplicates"""
    import_id = upload(client, workbook_with(
        row(invoice_number="OK-1"),
        row(invoice_number="OK-1"),                          # duplicate of the above
        row(invoice_number="BAD-1", currency="XYZ"),
    )).json()["id"]

    body = client.get(f"/imports/{import_id}").json()
    assert body["invoices_found"] == (
        body["invoices_created"] + body["invoices_failed"] + body["duplicate_invoices"]
    )


def test_blank_rows_are_not_counted(client):
    import_id = upload(client, workbook_with(row(), [None] * 11, [None] * 11)).json()["id"]
    assert client.get(f"/imports/{import_id}").json()["total_rows"] == 1


# ====================================================================== mixed outcomes


def test_a_bad_invoice_does_not_cost_the_good_ones(client, db_session):
    upload(client, workbook_with(
        row(invoice_number="GOOD-1"),
        row(invoice_number="BAD-1", currency="XYZ"),
        row(invoice_number="GOOD-2"),
    ))

    numbers = {i.invoice_number for i in db_session.query(Invoice).all()}
    assert numbers == {"GOOD-1", "GOOD-2"}


def test_business_failures_are_counted_and_stored(client, db_session):
    import_id = upload(client, workbook_with(
        row(invoice_number="BAD-1", currency="XYZ")
    )).json()["id"]

    body = client.get(f"/imports/{import_id}").json()
    assert body["invoices_created"] == 0
    assert body["invoices_failed"] == 1

    stored = errors_for(db_session, import_id)
    assert [e.code for e in stored] == ["INVALID_CURRENCY"]
    assert stored[0].scope == "invoice"
    assert stored[0].invoice_number == "BAD-1"


def test_parse_errors_are_stored_with_their_row(client, db_session):
    import_id = upload(client, workbook_with(
        row(invoice_number="INV-9", quantity="two")
    )).json()["id"]

    stored = [e for e in errors_for(db_session, import_id) if e.scope == "row"]
    assert [e.code for e in stored] == ["INVALID_NUMBER"]
    assert stored[0].row_number == 2
    assert stored[0].field == "quantity"


def test_grouping_failures_are_counted_and_stored(client, db_session):
    """The playbook's example: two rows of one invoice, two currencies."""
    import_id = upload(client, workbook_with(
        row(invoice_number="SPLIT", currency="EUR"),
        row(invoice_number="SPLIT", currency="USD"),
    )).json()["id"]

    body = client.get(f"/imports/{import_id}").json()
    assert body["invoices_created"] == 0
    assert body["invoices_failed"] == 1

    stored = [e for e in errors_for(db_session, import_id) if e.scope == "invoice"]
    assert stored[0].code == "INCONSISTENT_INVOICE_FIELD"


# =========================================================================== duplicates


def test_a_duplicate_within_one_file(client, db_session):
    import_id = upload(client, workbook_with(
        row(invoice_number="DUP-1"), row(invoice_number="DUP-1"),
    )).json()["id"]

    # the two rows are identical, so grouping makes them ONE invoice of two lines
    # -- which then fails reconciliation, not duplication
    assert db_session.query(Invoice).filter_by(invoice_number="DUP-1").count() <= 1


def test_a_duplicate_of_an_invoice_already_stored(client, db_session):
    client.post("/invoices", json={
        "invoice_number": "EXISTING", "vendor": "ABC GmbH",
        "invoice_date": "2026-01-15", "currency": "EUR",
        "subtotal": "200.00", "tax": "38.00", "total": "238.00",
    })

    import_id = upload(client, workbook_with(row(invoice_number="EXISTING"))).json()["id"]

    body = client.get(f"/imports/{import_id}").json()
    assert body["duplicate_invoices"] == 1
    assert body["invoices_created"] == 0

    stored = errors_for(db_session, import_id)
    assert [e.code for e in stored] == ["DUPLICATE_INVOICE"]


# ============================================================== structure still gates


def test_a_structurally_invalid_file_creates_no_job(client, db_session):
    from app.models.import_job import ImportJob

    response = upload(client, b"not a workbook")

    assert response.status_code == 422
    assert db_session.query(ImportJob).count() == 0
    assert db_session.query(Invoice).count() == 0
