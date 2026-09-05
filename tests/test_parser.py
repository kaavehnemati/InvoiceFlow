"""Row parsing: cells in, typed values or structured errors out.

Nothing here checks whether an invoice is any good. A row can parse perfectly
and describe an invoice with a negative quantity -- that is Phase 20's job.
"""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.services.excel_parser import ParsedRow, parse_rows
from app.services.excel_template import COLUMN_NAMES, SHEET_NAME, build_template_workbook

# A valid row, in the template's column order.
ROW = [
    "INV-2026-1001", "ABC GmbH", "2026-01-15", "Consulting",
    2, 100.00, 19, "EUR", 250.00, 47.50, 297.50,
]


def to_bytes(workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def sheet_with(*rows, header=None) -> bytes:
    """A minimal workbook -- header plus the given rows."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_NAME
    sheet.append(list(header or COLUMN_NAMES))
    for row in rows:
        sheet.append(list(row))
    return to_bytes(workbook)


def row_with(**overrides):
    values = dict(zip(COLUMN_NAMES, ROW))
    values.update(overrides)
    return [values[name] for name in COLUMN_NAMES]


def codes(errors) -> list[str]:
    return [e.code for e in errors]


# ------------------------------------------------------------- the happy path


def test_parses_the_published_template():
    workbook = load_workbook(BytesIO(build_template_workbook()))
    workbook[SHEET_NAME].append(ROW)
    workbook[SHEET_NAME].append(row_with(item="Travel", quantity=1, unit_price=50.00))

    rows, errors = parse_rows(to_bytes(workbook))

    assert errors == []
    assert len(rows) == 2
    assert all(isinstance(r, ParsedRow) for r in rows)


def test_values_come_back_typed():
    rows, _ = parse_rows(sheet_with(ROW))
    row = rows[0]

    assert row.invoice_number == "INV-2026-1001"
    assert row.invoice_date == date(2026, 1, 15)
    assert isinstance(row.invoice_date, date)
    assert row.quantity == Decimal("2")
    assert isinstance(row.quantity, Decimal)
    assert row.declared_total == Decimal("297.50")


# ------------------------------------------------------------- normalisation


def test_whitespace_is_stripped():
    rows, _ = parse_rows(
        sheet_with(row_with(invoice_number="  INV-2026-1001  ", vendor="  ABC GmbH "))
    )
    assert rows[0].invoice_number == "INV-2026-1001"
    assert rows[0].vendor == "ABC GmbH"


def test_currency_is_upper_cased():
    """Phase 4's rule is case-sensitive on purpose; normalising is this phase's job."""
    rows, errors = parse_rows(sheet_with(row_with(currency="  eur ")))
    assert errors == []
    assert rows[0].currency == "EUR"


def test_float_cells_do_not_bring_binary_noise():
    """Decimal(0.1) is 0.1000000000000000055...; going via str() is not."""
    rows, _ = parse_rows(sheet_with(row_with(quantity=0.1)))

    assert rows[0].quantity == Decimal("0.1")
    assert str(rows[0].quantity) == "0.1"


def test_integers_and_strings_both_become_decimals():
    rows, _ = parse_rows(sheet_with(row_with(quantity=3, unit_price="9.99")))
    assert rows[0].quantity == Decimal("3")
    assert rows[0].unit_price == Decimal("9.99")


# --------------------------------------------------------------------- dates


def test_a_real_date_cell():
    """What Excel gives for a date-formatted cell."""
    rows, errors = parse_rows(sheet_with(row_with(invoice_date=datetime(2026, 1, 15))))
    assert errors == []
    assert rows[0].invoice_date == date(2026, 1, 15)


def test_iso_text():
    rows, errors = parse_rows(sheet_with(row_with(invoice_date="2026-01-15")))
    assert errors == []
    assert rows[0].invoice_date == date(2026, 1, 15)


@pytest.mark.parametrize("value", ["15/01/2026", "01/02/2026", "15.01.2026", "Jan 15 2026"])
def test_ambiguous_or_regional_dates_are_refused(value):
    """01/02/2026 is 2 January or 1 February. Guessing is worse than refusing."""
    rows, errors = parse_rows(sheet_with(row_with(invoice_date=value)))

    assert rows == []
    assert codes(errors) == ["INVALID_DATE"]
    assert errors[0].field == "invoice_date"


# --------------------------------------------------------------- row errors


def test_missing_required_field_names_the_field():
    rows, errors = parse_rows(sheet_with(row_with(vendor=None)))

    assert rows == []
    assert codes(errors) == ["MISSING_REQUIRED_FIELD"]
    assert errors[0].field == "vendor"


def test_non_numeric_quantity():
    rows, errors = parse_rows(sheet_with(row_with(quantity="two")))

    assert rows == []
    assert codes(errors) == ["INVALID_NUMBER"]
    assert errors[0].field == "quantity"


def test_every_bad_cell_in_a_row_is_reported():
    """One resubmission should not be needed per mistake."""
    rows, errors = parse_rows(
        sheet_with(row_with(vendor=None, invoice_date="15/01/2026", quantity="two"))
    )

    assert rows == []
    assert {(e.field, e.code) for e in errors} == {
        ("vendor", "MISSING_REQUIRED_FIELD"),
        ("invoice_date", "INVALID_DATE"),
        ("quantity", "INVALID_NUMBER"),
    }


def test_a_bad_row_yields_no_parsed_row_and_a_good_one_still_parses():
    rows, errors = parse_rows(
        sheet_with(ROW, row_with(quantity="two"), row_with(item="Travel"))
    )

    assert len(rows) == 2
    assert len(errors) == 1
    # every non-blank row produced exactly one outcome
    assert {r.row_number for r in rows} | {e.row_number for e in errors} == {2, 3, 4}


# -------------------------------------------------------------- blank rows


def test_blank_rows_are_skipped():
    rows, errors = parse_rows(sheet_with(ROW, [None] * 11, [""] * 11, row_with(item="Travel")))

    assert len(rows) == 2
    assert errors == []


def test_a_mostly_blank_file_produces_no_noise():
    """Excel keeps rows whose contents were deleted."""
    rows, errors = parse_rows(sheet_with(ROW, *([[None] * 11] * 500)))

    assert len(rows) == 1
    assert errors == []


# ----------------------------------------------------------- row numbering


def test_row_numbers_match_the_spreadsheet():
    """An error about 'row 4' should mean the fourth row on screen."""
    rows, errors = parse_rows(sheet_with(ROW, ROW, row_with(quantity="two")))

    assert [r.row_number for r in rows] == [2, 3]
    assert errors[0].row_number == 4


# ------------------------------------------------------- column independence


def test_reordered_columns_still_parse():
    """Columns are found by name. Reading by position would misfile every value."""
    reordered = list(reversed(COLUMN_NAMES))
    values = dict(zip(COLUMN_NAMES, ROW))

    rows, errors = parse_rows(
        sheet_with([values[name] for name in reordered], header=reordered)
    )

    assert errors == []
    assert rows[0].vendor == "ABC GmbH"
    assert rows[0].currency == "EUR"
    assert rows[0].quantity == Decimal("2")


def test_extra_columns_are_ignored():
    header = list(COLUMN_NAMES) + ["internal_note"]
    rows, errors = parse_rows(sheet_with(ROW + ["ignore me"], header=header))

    assert errors == []
    assert rows[0].invoice_number == "INV-2026-1001"


# ----------------------------------------- parsing is not business validation


def test_a_row_can_parse_and_still_be_a_terrible_invoice():
    """Negative quantity, impossible tax rate, totals that do not add up.

    All of it parses. Whether it is acceptable is Phase 20's question.
    """
    rows, errors = parse_rows(
        sheet_with(
            row_with(quantity=-5, unit_price=-100.00, tax_rate=900, declared_total=0.01)
        )
    )

    assert errors == []
    assert rows[0].quantity == Decimal("-5")
    assert rows[0].tax_rate == Decimal("900")
