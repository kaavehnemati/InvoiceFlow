"""Turning spreadsheet cells into typed application data.

A cell is not a value. It is whatever Excel felt like storing -- a float where
you wanted a decimal, a datetime where you wanted a date, a string with a
trailing space someone never saw. This module is the boundary where that
becomes typed data or an error, and nothing downstream should have to think
about cells again.

It does not decide whether an invoice is any good: a row can parse perfectly
and still describe an invoice with a negative quantity. That is Phase 20's
question. This module only asks whether the cell can be read at all.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import load_workbook

from app.services.excel_template import COLUMN_NAMES, SHEET_NAME

_TEXT_FIELDS = ("invoice_number", "vendor", "item", "currency")
_DECIMAL_FIELDS = (
    "quantity",
    "unit_price",
    "tax_rate",
    "declared_subtotal",
    "declared_tax",
    "declared_total",
)


@dataclass(frozen=True)
class ParsedRow:
    """One spreadsheet row, as typed values."""

    row_number: int
    invoice_number: str
    vendor: str
    invoice_date: date
    item: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    currency: str
    declared_subtotal: Decimal
    declared_tax: Decimal
    declared_total: Decimal


@dataclass(frozen=True)
class RowError:
    """One thing wrong with one cell.

    row_number is the number Excel shows in its own gutter, so an error about
    "row 4" points at the line the user is looking at.
    """

    row_number: int
    field: str
    code: str
    message: str


def _to_text(value) -> str:
    """Trim whitespace nobody can see and would otherwise never find."""
    return "" if value is None else str(value).strip()


def _to_date(value):
    """A date cell, or ISO text. Deliberately nothing else.

    Excel hands back a datetime for a date-formatted cell and a string for a
    text one, so both are accepted. Regional formats are not: 01/02/2026 is
    2 January or 1 February depending on who typed it, and an invoice silently
    dated five weeks wrong is worse than an invoice rejected.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_to_text(value))
    except ValueError:
        return None


def _to_decimal(value):
    """A number, without letting binary floating point in.

    Excel stores numbers as floats, and Decimal(0.1) is
    0.1000000000000000055511151231257827. Going through str() keeps the value
    the user actually typed -- the same reason Phase 2 chose Decimal at all.
    """
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def parse_rows(content: bytes) -> tuple[list[ParsedRow], list[RowError]]:
    """Parse every data row into typed values, or into errors.

    Assumes the workbook's structure has already been checked -- Phase 17's
    validate_workbook_structure is that gate, and re-checking here would give
    one responsibility two owners.

    Every non-blank row produces exactly one outcome: a ParsedRow, or one or
    more RowErrors. Never both, never neither. A row with three unreadable
    cells reports all three, so somebody fixing a spreadsheet is not made to
    resubmit to discover the next problem.

    Entirely blank rows are skipped. Excel keeps rows whose contents were
    deleted, and a file with three invoices and nine hundred leftover rows
    should not produce nine hundred complaints.
    """
    workbook = load_workbook(BytesIO(content), data_only=True)
    sheet = workbook[SHEET_NAME]

    # By name, not position. A user who reorders columns still gets a working
    # import; reading by index would quietly put the vendor in the date field.
    header = [_to_text(cell.value) for cell in sheet[1]]
    index_of = {name: header.index(name) for name in COLUMN_NAMES}

    rows: list[ParsedRow] = []
    errors: list[RowError] = []

    for row_number, cells in enumerate(
        sheet.iter_rows(min_row=2, values_only=True), start=2
    ):
        if all(_to_text(cell) == "" for cell in cells):
            continue

        def cell(name: str):
            position = index_of[name]
            return cells[position] if position < len(cells) else None

        row_errors: list[RowError] = []

        def fail(field: str, code: str, message: str) -> None:
            row_errors.append(RowError(row_number, field, code, message))

        values: dict = {}

        for field in _TEXT_FIELDS:
            text = _to_text(cell(field))
            if not text:
                fail(field, "MISSING_REQUIRED_FIELD", f"{field} is required")
            # Currencies are compared against a fixed set that is uppercase.
            # Phase 4's rule is deliberately case-sensitive; normalising here
            # is what its test meant by "Phase 18's job".
            values[field] = text.upper() if field == "currency" else text

        raw_date = cell("invoice_date")
        if _to_text(raw_date) == "":
            fail("invoice_date", "MISSING_REQUIRED_FIELD", "invoice_date is required")
        else:
            parsed_date = _to_date(raw_date)
            if parsed_date is None:
                fail(
                    "invoice_date",
                    "INVALID_DATE",
                    f"{raw_date!r} is not a date. Use YYYY-MM-DD.",
                )
            else:
                values["invoice_date"] = parsed_date

        for field in _DECIMAL_FIELDS:
            raw = cell(field)
            if _to_text(raw) == "":
                fail(field, "MISSING_REQUIRED_FIELD", f"{field} is required")
                continue
            number = _to_decimal(raw)
            if number is None:
                fail(field, "INVALID_NUMBER", f"{raw!r} is not a number")
            else:
                values[field] = number

        if row_errors:
            errors.extend(row_errors)
        else:
            rows.append(ParsedRow(row_number=row_number, **values))

    return rows, errors
