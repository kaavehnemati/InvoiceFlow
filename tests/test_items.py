"""Invoice items: per-line rules, derived amounts, and reconciliation."""
from decimal import Decimal

import pytest

from app.core.exceptions import InvoiceValidationError
from app.schemas.invoice import InvoiceItemCreate
from app.services.invoice_service import InvoiceService, derive_line_amounts


def item(**overrides) -> InvoiceItemCreate:
    defaults = {
        "description": "Consulting",
        "quantity": Decimal("2"),
        "unit_price": Decimal("100.00"),
        "tax_rate": Decimal("19"),
    }
    return InvoiceItemCreate(**{**defaults, **overrides})


@pytest.fixture
def validate():
    service = InvoiceService(repository=None)
    return lambda data: sorted(i["code"] for i in service.validate(data))


# --------------------------------------------------------------- derivation


def test_derives_line_amounts():
    line_subtotal, line_tax, line_total = derive_line_amounts(item())

    assert line_subtotal == Decimal("200.00")   # 2 x 100.00
    assert line_tax == Decimal("38.00")         # 19% of 200.00
    assert line_total == Decimal("238.00")


def test_tax_rate_is_a_percentage_not_a_fraction():
    """19 means 19%. Multiplying by 19 directly would be 100x too much."""
    _, line_tax, _ = derive_line_amounts(
        item(quantity=Decimal("1"), unit_price=Decimal("100.00"))
    )
    assert line_tax == Decimal("19.00")


def test_rounds_each_line_to_cents():
    """3 x 9.99 = 29.97; 19% of that is 5.6943, which is not a real amount."""
    line_subtotal, line_tax, line_total = derive_line_amounts(
        item(quantity=Decimal("3"), unit_price=Decimal("9.99"))
    )

    assert line_subtotal == Decimal("29.97")
    assert line_tax == Decimal("5.69")          # 5.6943 rounded, not truncated
    assert line_total == Decimal("35.66")
    assert line_subtotal + line_tax == line_total


def test_rounds_the_subtotal_too_not_just_the_tax():
    """1.555 x 3.00 = 4.665, which is not a real amount either.

    Added after a deliberate regression check: removing the quantize from
    line_subtotal passed the entire suite, because every other case happened to
    multiply out to exactly two decimals. The rounding was covered by
    inspection, not by a test.
    """
    line_subtotal, line_tax, line_total = derive_line_amounts(
        item(quantity=Decimal("1.555"), unit_price=Decimal("3.00"))
    )

    assert line_subtotal == Decimal("4.67")     # 4.665 rounded half-up
    assert line_tax == Decimal("0.89")          # 19% of 4.67 = 0.8873
    assert line_total == Decimal("5.56")
    assert line_subtotal.as_tuple().exponent == -2


def test_fractional_quantities_are_allowed():
    line_subtotal, _, _ = derive_line_amounts(
        item(quantity=Decimal("2.5"), unit_price=Decimal("80.00"))
    )
    assert line_subtotal == Decimal("200.00")


def test_zero_tax_rate():
    line_subtotal, line_tax, line_total = derive_line_amounts(
        item(tax_rate=Decimal("0"))
    )
    assert line_tax == Decimal("0.00")
    assert line_total == line_subtotal


# ------------------------------------------------------------- per-item rules


def test_quantity_must_be_positive(validate, make_invoice):
    data = make_invoice(
        items=[item(quantity=Decimal("0"))],
        subtotal=Decimal("0"), tax=Decimal("0"), total=Decimal("0"),
    )
    assert "INVALID_QUANTITY" in validate(data)


def test_negative_quantity(validate, make_invoice):
    data = make_invoice(
        items=[item(quantity=Decimal("-1"))],
        subtotal=Decimal("0"), tax=Decimal("0"), total=Decimal("0"),
    )
    assert "INVALID_QUANTITY" in validate(data)


def test_negative_unit_price(validate, make_invoice):
    data = make_invoice(
        items=[item(unit_price=Decimal("-1.00"))],
        subtotal=Decimal("0"), tax=Decimal("0"), total=Decimal("0"),
    )
    assert "NEGATIVE_AMOUNT" in validate(data)


@pytest.mark.parametrize("rate", [Decimal("-1"), Decimal("101")])
def test_tax_rate_out_of_range(validate, make_invoice, rate):
    data = make_invoice(
        items=[item(tax_rate=rate)],
        subtotal=Decimal("0"), tax=Decimal("0"), total=Decimal("0"),
    )
    assert "INVALID_TAX_RATE" in validate(data)


@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("100")])
def test_tax_rate_bounds_are_inclusive(rate):
    """0 <= tax_rate <= 100, so both ends are valid."""
    _, line_tax, _ = derive_line_amounts(
        item(quantity=Decimal("1"), unit_price=Decimal("100.00"), tax_rate=rate)
    )
    assert line_tax == (Decimal("0.00") if rate == 0 else Decimal("100.00"))


def test_the_offending_line_is_identified(make_invoice):
    service = InvoiceService(repository=None)
    data = make_invoice(
        items=[item(), item(quantity=Decimal("0"))],
        subtotal=Decimal("0"), tax=Decimal("0"), total=Decimal("0"),
    )
    fields = [i["field"] for i in service.validate(data)]
    assert "items[1].quantity" in fields


# ------------------------------------------------------------ reconciliation


def test_totals_matching_the_lines_are_accepted(validate, make_invoice):
    data = make_invoice(
        items=[item()],
        subtotal=Decimal("200.00"), tax=Decimal("38.00"), total=Decimal("238.00"),
    )
    assert validate(data) == []


def test_two_lines_sum_correctly(validate, make_invoice):
    data = make_invoice(
        items=[item(), item(quantity=Decimal("1"), unit_price=Decimal("50.00"))],
        subtotal=Decimal("250.00"),     # 200.00 + 50.00
        tax=Decimal("47.50"),           # 38.00 + 9.50
        total=Decimal("297.50"),
    )
    assert validate(data) == []


def test_subtotal_disagreeing_with_lines(validate, make_invoice):
    data = make_invoice(
        items=[item()],
        subtotal=Decimal("999.00"), tax=Decimal("38.00"), total=Decimal("1037.00"),
    )
    assert "LINE_TOTAL_MISMATCH" in validate(data)


def test_tax_disagreeing_with_lines(make_invoice):
    service = InvoiceService(repository=None)
    data = make_invoice(
        items=[item()],
        subtotal=Decimal("200.00"), tax=Decimal("10.00"), total=Decimal("210.00"),
    )
    by_field = {i["field"]: i["code"] for i in service.validate(data)}
    assert by_field["tax"] == "TAX_MISMATCH"


def test_broken_lines_suppress_reconciliation_noise(make_invoice):
    """A bad quantity makes the sums meaningless; report the cause, not the effect."""
    service = InvoiceService(repository=None)
    data = make_invoice(
        items=[item(quantity=Decimal("0"))],
        subtotal=Decimal("200.00"), tax=Decimal("38.00"), total=Decimal("238.00"),
    )
    codes = [i["code"] for i in service.validate(data)]
    assert codes == ["INVALID_QUANTITY"]


def test_header_only_invoices_are_still_valid(validate, make_invoice):
    assert validate(make_invoice()) == []


# ------------------------------------------------------------------- storage


def test_items_are_persisted_with_the_invoice(service, repository, make_invoice):
    created = service.create(
        make_invoice(
            invoice_number="ITEMS-1",
            items=[item(), item(quantity=Decimal("1"), unit_price=Decimal("50.00"))],
            subtotal=Decimal("250.00"), tax=Decimal("47.50"), total=Decimal("297.50"),
        )
    )

    reloaded = repository.get_by_id(created.id)
    assert len(reloaded.items) == 2
    assert [i.id for i in reloaded.items] == sorted(i.id for i in reloaded.items)
    assert reloaded.items[0].line_total == Decimal("238.00")


def test_stored_lines_sum_to_the_stored_totals(service, repository, make_invoice):
    """The Definition of Done, at the database level."""
    created = service.create(
        make_invoice(
            invoice_number="ITEMS-2",
            items=[
                item(quantity=Decimal("3"), unit_price=Decimal("9.99")),
                item(quantity=Decimal("1"), unit_price=Decimal("100.00")),
            ],
            subtotal=Decimal("129.97"),   # 29.97 + 100.00
            tax=Decimal("24.69"),         # 5.69 + 19.00
            total=Decimal("154.66"),
        )
    )
    stored = repository.get_by_id(created.id)

    assert sum(i.line_subtotal for i in stored.items) == stored.subtotal
    assert sum(i.line_tax for i in stored.items) == stored.tax
    assert sum(i.line_total for i in stored.items) == stored.total


def test_rejected_invoice_stores_no_items(service, repository, make_invoice):
    with pytest.raises(InvoiceValidationError):
        service.create(
            make_invoice(
                invoice_number="ITEMS-3",
                items=[item()],
                subtotal=Decimal("1.00"), tax=Decimal("0.00"), total=Decimal("1.00"),
            )
        )
    assert repository.find_by_vendor_and_invoice_number("ABC GmbH", "ITEMS-3") is None


def test_deleting_an_invoice_deletes_its_items(service, db_session, make_invoice):
    from sqlalchemy import func, select

    from app.models.invoice import InvoiceItem

    created = service.create(
        make_invoice(
            invoice_number="ITEMS-4",
            items=[item()],
            subtotal=Decimal("200.00"), tax=Decimal("38.00"), total=Decimal("238.00"),
        )
    )
    invoice_id = created.id

    db_session.delete(created)
    db_session.flush()

    remaining = db_session.scalar(
        select(func.count()).select_from(InvoiceItem).where(
            InvoiceItem.invoice_id == invoice_id
        )
    )
    assert remaining == 0
