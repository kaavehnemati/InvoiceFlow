"""Grouping rows into invoices, and catching rows that disagree.

Nothing here decides whether an invoice is acceptable -- a group can hold
together perfectly and still describe an invoice with a negative quantity.
That is Phase 20's question.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.services.excel_grouper import GroupedInvoice, group_rows
from app.services.excel_parser import ParsedRow, RowError


def row(row_number, invoice_number="INV-1001", vendor="ABC GmbH", **overrides):
    defaults = dict(
        invoice_date=date(2026, 1, 15),
        item="Consulting",
        quantity=Decimal("2"),
        unit_price=Decimal("100.00"),
        tax_rate=Decimal("19"),
        currency="EUR",
        declared_subtotal=Decimal("250.00"),
        declared_tax=Decimal("47.50"),
        declared_total=Decimal("297.50"),
    )
    defaults.update(overrides)
    return ParsedRow(
        row_number=row_number,
        invoice_number=invoice_number,
        vendor=vendor,
        **defaults,
    )


def codes(errors):
    return [e.code for e in errors]


# ------------------------------------------------------- the Definition of Done


def test_one_multi_line_invoice_becomes_one_invoice_with_many_items():
    invoices, errors = group_rows(
        [
            row(2, item="Consulting"),
            row(3, item="Travel"),
            row(4, item="Materials"),
        ],
        [],
    )

    assert errors == []
    assert len(invoices) == 1

    invoice = invoices[0]
    assert isinstance(invoice, GroupedInvoice)
    assert invoice.invoice_number == "INV-1001"
    assert [i.description for i in invoice.items] == ["Consulting", "Travel", "Materials"]
    assert invoice.row_numbers == [2, 3, 4]


def test_the_sheets_item_becomes_the_domains_description():
    invoices, _ = group_rows([row(2, item="Consulting hours")], [])
    assert invoices[0].items[0].description == "Consulting hours"


def test_invoice_level_fields_come_from_the_rows():
    invoices, _ = group_rows([row(2), row(3)], [])
    invoice = invoices[0]

    assert invoice.invoice_date == date(2026, 1, 15)
    assert invoice.currency == "EUR"
    assert invoice.declared_total == Decimal("297.50")


# ------------------------------------------------------------------ grouping


def test_two_invoices_interleaved_in_the_file():
    invoices, errors = group_rows(
        [
            row(2, invoice_number="INV-1001", item="A"),
            row(3, invoice_number="INV-1002", item="B"),
            row(4, invoice_number="INV-1001", item="C"),
        ],
        [],
    )

    assert errors == []
    assert len(invoices) == 2
    by_number = {i.invoice_number: i for i in invoices}
    assert [i.description for i in by_number["INV-1001"].items] == ["A", "C"]
    assert [i.description for i in by_number["INV-1002"].items] == ["B"]


def test_same_number_different_vendor_stays_two_invoices():
    invoices, _ = group_rows(
        [row(2, vendor="ABC GmbH"), row(3, vendor="Other Ltd")], []
    )
    assert len(invoices) == 2


def test_matching_is_exact():
    """The same rule Phase 9's duplicate check uses, so the two cannot disagree."""
    invoices, _ = group_rows(
        [row(2, vendor="ABC GmbH"), row(3, vendor="abc gmbh")], []
    )
    assert len(invoices) == 2


def test_invoices_come_back_in_first_appearance_order():
    invoices, _ = group_rows(
        [
            row(2, invoice_number="INV-B"),
            row(3, invoice_number="INV-A"),
            row(4, invoice_number="INV-B"),
        ],
        [],
    )
    assert [i.invoice_number for i in invoices] == ["INV-B", "INV-A"]


def test_no_rows_gives_no_invoices():
    assert group_rows([], []) == ([], [])


# -------------------------------------------------------- cross-row consistency


def test_the_playbooks_example():
    """INV-1001 row 2 currency = EUR, row 3 currency = USD. Flag it."""
    invoices, errors = group_rows([row(2, currency="EUR"), row(3, currency="USD")], [])

    assert invoices == []
    assert codes(errors) == ["INCONSISTENT_INVOICE_FIELD"]
    assert errors[0].field == "currency"
    assert errors[0].invoice_number == "INV-1001"
    assert "EUR" in errors[0].message and "USD" in errors[0].message


@pytest.mark.parametrize(
    "field,other",
    [
        ("invoice_date", date(2026, 2, 20)),
        ("currency", "USD"),
        ("declared_subtotal", Decimal("999.00")),
        ("declared_tax", Decimal("1.00")),
        ("declared_total", Decimal("1.00")),
    ],
)
def test_every_invoice_level_field_is_checked(field, other):
    invoices, errors = group_rows([row(2), row(3, **{field: other})], [])

    assert invoices == []
    assert codes(errors) == ["INCONSISTENT_INVOICE_FIELD"]
    assert errors[0].field == field


def test_the_message_names_the_disagreeing_rows():
    _, errors = group_rows([row(2, currency="EUR"), row(3, currency="USD")], [])
    assert "row 2" in errors[0].message
    assert "row 3" in errors[0].message


def test_several_disagreements_are_all_reported():
    invoices, errors = group_rows(
        [row(2), row(3, currency="USD", declared_total=Decimal("1.00"))], []
    )

    assert invoices == []
    assert {e.field for e in errors} == {"currency", "declared_total"}


def test_a_disagreement_does_not_affect_other_invoices():
    invoices, errors = group_rows(
        [
            row(2, invoice_number="BROKEN", currency="EUR"),
            row(3, invoice_number="BROKEN", currency="USD"),
            row(4, invoice_number="FINE"),
        ],
        [],
    )

    assert [i.invoice_number for i in invoices] == ["FINE"]
    assert errors[0].invoice_number == "BROKEN"


def test_line_level_fields_may_differ_freely():
    """Different items, quantities and prices are the point of line items."""
    invoices, errors = group_rows(
        [
            row(2, item="A", quantity=Decimal("1"), unit_price=Decimal("10.00")),
            row(3, item="B", quantity=Decimal("7"), unit_price=Decimal("99.99")),
        ],
        [],
    )

    assert errors == []
    assert len(invoices) == 1
    assert len(invoices[0].items) == 2


# --------------------------------------------------------- incomplete invoices


def failed(row_number, invoice_number="INV-1001", vendor="ABC GmbH"):
    return RowError(
        row_number=row_number,
        field="quantity",
        code="INVALID_NUMBER",
        message="'two' is not a number",
        invoice_number=invoice_number,
        vendor=vendor,
    )


def test_an_invoice_missing_a_line_is_rejected_whole():
    """Building it from the survivors would produce a misleading totals error."""
    invoices, errors = group_rows([row(2), row(3)], [failed(4)])

    assert invoices == []
    assert codes(errors) == ["INCOMPLETE_INVOICE"]
    assert "row(s) 4" in errors[0].message


def test_an_incomplete_invoice_does_not_affect_others():
    invoices, errors = group_rows(
        [row(2, invoice_number="PARTIAL"), row(3, invoice_number="FINE")],
        [failed(4, invoice_number="PARTIAL")],
    )

    assert [i.invoice_number for i in invoices] == ["FINE"]
    assert codes(errors) == ["INCOMPLETE_INVOICE"]
    assert errors[0].invoice_number == "PARTIAL"


def test_rows_that_all_failed_still_report_their_invoice():
    """No row survived, so there is nothing to group -- but somebody meant to import it."""
    invoices, errors = group_rows([], [failed(2), failed(3)])

    assert invoices == []
    assert codes(errors) == ["INCOMPLETE_INVOICE"]
    assert errors[0].invoice_number == "INV-1001"
    assert "2, 3" in errors[0].message


def test_multiple_failed_rows_of_one_invoice_are_reported_once():
    invoices, errors = group_rows([row(2)], [failed(3), failed(4)])

    assert invoices == []
    assert len(errors) == 1
    assert "3, 4" in errors[0].message


def test_incompleteness_is_reported_instead_of_inconsistency():
    """One cause, not two symptoms."""
    invoices, errors = group_rows(
        [row(2, currency="EUR"), row(3, currency="USD")], [failed(4)]
    )

    assert invoices == []
    assert codes(errors) == ["INCOMPLETE_INVOICE"]
