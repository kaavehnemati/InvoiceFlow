"""Turning rows back into invoices.

A spreadsheet does not contain rows, it contains invoices. An invoice with
three lines takes three rows, repeating its invoice-level columns on each --
and that repetition creates a failure mode a single row can never have: two
rows claiming to be the same invoice while disagreeing about it.

    INV-1001 row 2 currency = EUR
    INV-1001 row 3 currency = USD

Neither row is wrong on its own. The invoice is.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.excel_parser import ParsedRow, RowError

# The columns that describe the invoice rather than the line. They repeat on
# every row of an invoice, so every row of an invoice must agree about them.
# invoice_number and vendor are the grouping key, so they agree by construction.
_INVOICE_FIELDS = (
    "invoice_date",
    "currency",
    "declared_subtotal",
    "declared_tax",
    "declared_total",
)


@dataclass(frozen=True)
class GroupedItem:
    """One line of an invoice.

    The sheet's column is called "item"; the domain calls it "description".
    This is the boundary where the spreadsheet's vocabulary becomes the
    application's.
    """

    row_number: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal


@dataclass(frozen=True)
class GroupedInvoice:
    invoice_number: str
    vendor: str
    invoice_date: date
    currency: str
    declared_subtotal: Decimal
    declared_tax: Decimal
    declared_total: Decimal
    items: list[GroupedItem]
    row_numbers: list[int]


@dataclass(frozen=True)
class InvoiceError:
    """Something wrong with an invoice rather than with one cell.

    Phase 21's report distinguishes the two:

        Row 12      -> missing vendor
        Invoice ... -> total mismatch
    """

    invoice_number: str
    vendor: str
    field: str | None
    code: str
    message: str
    row_numbers: list[int]


def group_rows(
    rows: list[ParsedRow], row_errors: list[RowError]
) -> tuple[list[GroupedInvoice], list[InvoiceError]]:
    """Group parsed rows into invoices, flagging any that do not hold together.

    Grouping is on vendor + invoice_number, compared exactly. That is the same
    rule Phase 9's duplicate check uses; normalising differently here would
    mean the two disagree about what counts as the same invoice.

    row_errors are passed in so an invoice missing one of its lines can be
    rejected whole. Building it from the rows that happened to parse would
    produce a misleading error later -- "subtotal is 250.00 but lines sum to
    200.00" sends someone hunting an arithmetic mistake when the cause is one
    unreadable cell.

    Invoices come back in first-appearance order and their items in sheet
    order, so a report reads in the same order as the spreadsheet.
    """
    grouped: dict[tuple[str, str], list[ParsedRow]] = {}
    for row in rows:
        grouped.setdefault((row.vendor, row.invoice_number), []).append(row)

    # Which invoices lost a row to a parse failure.
    failed_rows: dict[tuple[str, str], list[int]] = {}
    for error in row_errors:
        key = (error.vendor, error.invoice_number)
        numbers = failed_rows.setdefault(key, [])
        if error.row_number not in numbers:
            numbers.append(error.row_number)

    invoices: list[GroupedInvoice] = []
    errors: list[InvoiceError] = []

    for key, invoice_rows in grouped.items():
        vendor, invoice_number = key
        row_numbers = [row.row_number for row in invoice_rows]

        if key in failed_rows:
            unreadable = sorted(failed_rows.pop(key))
            errors.append(
                InvoiceError(
                    invoice_number=invoice_number,
                    vendor=vendor,
                    field=None,
                    code="INCOMPLETE_INVOICE",
                    message=(
                        f"row(s) {', '.join(str(n) for n in unreadable)} could not "
                        f"be read, so this invoice is missing at least one line item"
                    ),
                    row_numbers=sorted(row_numbers + unreadable),
                )
            )
            continue

        inconsistencies = _find_inconsistencies(invoice_rows)
        if inconsistencies:
            for field, values in inconsistencies:
                errors.append(
                    InvoiceError(
                        invoice_number=invoice_number,
                        vendor=vendor,
                        field=field,
                        code="INCONSISTENT_INVOICE_FIELD",
                        message=(
                            f"rows of this invoice disagree about {field}: "
                            + "; ".join(
                                f"row {number} says {value}"
                                for number, value in values
                            )
                        ),
                        row_numbers=row_numbers,
                    )
                )
            continue

        first = invoice_rows[0]
        invoices.append(
            GroupedInvoice(
                invoice_number=invoice_number,
                vendor=vendor,
                invoice_date=first.invoice_date,
                currency=first.currency,
                declared_subtotal=first.declared_subtotal,
                declared_tax=first.declared_tax,
                declared_total=first.declared_total,
                items=[
                    GroupedItem(
                        row_number=row.row_number,
                        description=row.item,
                        quantity=row.quantity,
                        unit_price=row.unit_price,
                        tax_rate=row.tax_rate,
                    )
                    for row in invoice_rows
                ],
                row_numbers=row_numbers,
            )
        )

    # Rows that failed to parse and share no key with any surviving row still
    # describe an invoice nobody can build.
    for (vendor, invoice_number), unreadable in failed_rows.items():
        errors.append(
            InvoiceError(
                invoice_number=invoice_number,
                vendor=vendor,
                field=None,
                code="INCOMPLETE_INVOICE",
                message=(
                    f"row(s) {', '.join(str(n) for n in sorted(unreadable))} could "
                    f"not be read, so no invoice could be built from them"
                ),
                row_numbers=sorted(unreadable),
            )
        )

    return invoices, errors


def _find_inconsistencies(
    invoice_rows: list[ParsedRow],
) -> list[tuple[str, list[tuple[int, object]]]]:
    """Which invoice-level fields the rows disagree about, and what they say.

    No value wins. There is no first-row-wins or majority rule, because the
    data does not say which reading is right and guessing produces a plausible
    wrong answer instead of a visible error. Every distinct value is reported
    with the row that claimed it.
    """
    found = []
    for field in _INVOICE_FIELDS:
        seen: dict[object, int] = {}
        for row in invoice_rows:
            value = getattr(row, field)
            seen.setdefault(value, row.row_number)
        if len(seen) > 1:
            found.append((field, [(number, value) for value, number in seen.items()]))
    return found
