"""GET /imports/{import_id}/errors -- actionable detail behind the counts.

The Definition of Done is that a business user can understand what needs to
be corrected in the source spreadsheet. Everything here is checked against
that: does the response name the row or invoice, the field, and read like
something a person (not just software) can act on.
"""
from io import BytesIO

from openpyxl import load_workbook

from app.services.excel_template import SHEET_NAME, build_template_workbook

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


# ============================================================ the Definition of Done


def test_a_missing_field_reads_as_a_row_problem(client):
    """The playbook's own shape: "Row 12 -> missing vendor".

    A single unreadable cell produces two stored errors -- the row-level
    parse failure, and the invoice-level INCOMPLETE_INVOICE that grouping
    correctly raises because the invoice is now missing a line (Phase 19/20's
    cascade). Both are legitimate; this test checks the row-scoped one.
    """
    import_id = upload(client, workbook_with(row(quantity="two"))).json()["id"]

    errors = client.get(f"/imports/{import_id}/errors").json()["errors"]
    row_errors = [e for e in errors if e["scope"] == "row"]

    assert len(row_errors) == 1
    error = row_errors[0]
    assert error["row_number"] == 2
    assert error["field"] == "quantity"
    assert error["summary"] == "Row 2 → 'two' is not a number"


def test_a_duplicate_reads_as_an_invoice_problem(client):
    """The playbook's other shape: "Invoice INV-1008 -> duplicate invoice"."""
    client.post("/invoices", json={
        "invoice_number": "INV-1001", "vendor": "ABC GmbH",
        "invoice_date": "2026-01-15", "currency": "EUR",
        "subtotal": "200.00", "tax": "38.00", "total": "238.00",
    })

    import_id = upload(client, workbook_with(row())).json()["id"]
    errors = client.get(f"/imports/{import_id}/errors").json()["errors"]

    assert len(errors) == 1
    error = errors[0]
    assert error["scope"] == "invoice"
    assert error["invoice_number"] == "INV-1001"
    assert error["code"] == "DUPLICATE_INVOICE"
    assert error["summary"].startswith("Invoice INV-1001 → ")


def test_a_business_user_can_see_what_to_fix(client):
    """A realistic mixed file, read as a whole -- the actual claim of this phase."""
    import_id = upload(client, workbook_with(
        row(invoice_number="OK", currency="XYZ"),
        row(invoice_number="ALSO-BAD", quantity="two"),
    )).json()["id"]

    summaries = [e["summary"] for e in client.get(f"/imports/{import_id}/errors").json()["errors"]]

    assert any("Invoice OK" in s and "currency" in s.lower() for s in summaries)
    assert any(s.startswith("Row ") and "number" in s.lower() for s in summaries)


# --------------------------------------------------------------- scope shapes


def test_row_errors_always_carry_a_row_number(client):
    """row_number is what distinguishes a row error, not the absence of identity.

    invoice_number/vendor are populated too when the row's identity cells were
    readable -- that is deliberate (Phase 19 needs it to attribute a failed
    row to its invoice), not a leak between the two scopes.
    """
    import_id = upload(client, workbook_with(row(quantity="two"))).json()["id"]
    row_error = next(
        e for e in client.get(f"/imports/{import_id}/errors").json()["errors"]
        if e["scope"] == "row"
    )

    assert row_error["row_number"] == 2
    assert row_error["invoice_number"] == "INV-1001"  # readable, so populated


def test_invoice_errors_carry_no_row_number(client):
    """The distinguishing fact for scope="invoice": there is no single row."""
    import_id = upload(client, workbook_with(row(currency="XYZ"))).json()["id"]
    error = client.get(f"/imports/{import_id}/errors").json()["errors"][0]

    assert error["scope"] == "invoice"
    assert error["invoice_number"] == "INV-1001"
    assert error["row_number"] is None


# ---------------------------------------------------------------------- empty


def test_an_import_with_no_errors_returns_200_and_an_empty_list(client):
    import_id = upload(client, workbook_with(row())).json()["id"]

    response = client.get(f"/imports/{import_id}/errors")

    assert response.status_code == 200
    assert response.json() == {"total": 0, "limit": 100, "offset": 0, "errors": []}


def test_unknown_import_is_404(client):
    response = client.get("/imports/imp_doesnotexist/errors")
    assert response.status_code == 404
    assert response.json() == {"detail": "Import not found"}


# ----------------------------------------------------------------- pagination


def test_default_pagination(client):
    import_id = upload(client, workbook_with(
        row(invoice_number="A", currency="XYZ"),
        row(invoice_number="B", currency="XYZ"),
        row(invoice_number="C", currency="XYZ"),
    )).json()["id"]

    body = client.get(f"/imports/{import_id}/errors").json()

    assert body["total"] == 3
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert len(body["errors"]) == 3


def test_limit_restricts_the_page_but_not_the_total(client):
    import_id = upload(client, workbook_with(
        row(invoice_number="A", currency="XYZ"),
        row(invoice_number="B", currency="XYZ"),
        row(invoice_number="C", currency="XYZ"),
    )).json()["id"]

    body = client.get(f"/imports/{import_id}/errors?limit=2").json()

    assert body["total"] == 3
    assert body["limit"] == 2
    assert len(body["errors"]) == 2


def test_offset_skips_correctly(client):
    import_id = upload(client, workbook_with(
        row(invoice_number="A", currency="XYZ"),
        row(invoice_number="B", currency="XYZ"),
        row(invoice_number="C", currency="XYZ"),
    )).json()["id"]

    first_page = client.get(f"/imports/{import_id}/errors?limit=2&offset=0").json()
    second_page = client.get(f"/imports/{import_id}/errors?limit=2&offset=2").json()

    assert len(first_page["errors"]) == 2
    assert len(second_page["errors"]) == 1
    seen = {e["invoice_number"] for e in first_page["errors"] + second_page["errors"]}
    assert seen == {"A", "B", "C"}


def test_errors_are_returned_in_a_stable_order(client):
    import_id = upload(client, workbook_with(
        row(invoice_number="A", currency="XYZ"),
        row(invoice_number="B", currency="XYZ"),
    )).json()["id"]

    first = client.get(f"/imports/{import_id}/errors").json()["errors"]
    second = client.get(f"/imports/{import_id}/errors").json()["errors"]

    assert [e["invoice_number"] for e in first] == [e["invoice_number"] for e in second]


def test_limit_and_offset_are_validated(client):
    import_id = upload(client, workbook_with(row())).json()["id"]

    assert client.get(f"/imports/{import_id}/errors?limit=0").status_code == 422
    assert client.get(f"/imports/{import_id}/errors?offset=-1").status_code == 422
    assert client.get(f"/imports/{import_id}/errors?limit=1001").status_code == 422
