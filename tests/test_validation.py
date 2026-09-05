"""Unit tests: the business rules on their own.

No database, no HTTP, no fixtures that need either. InvoiceService.validate()
is pure, so these construct a service with no repository at all -- which is
itself the point being tested.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.services.invoice_service import InvoiceService
from tests.conftest import TODAY


@pytest.fixture
def validate():
    """validate() never touches the repository, so None is a valid one."""
    service = InvoiceService(repository=None)
    return lambda data: sorted(i["code"] for i in service.validate(data))


def test_valid_invoice_has_no_issues(validate, make_invoice):
    assert validate(make_invoice()) == []


def test_invalid_total(validate, make_invoice):
    # The playbook's own example: 1000 + 190 != 1300
    data = make_invoice(
        subtotal=Decimal("1000"), tax=Decimal("190"), total=Decimal("1300")
    )
    assert validate(data) == ["TOTAL_MISMATCH"]


def test_future_date(validate, make_invoice):
    assert validate(make_invoice(invoice_date=TODAY + timedelta(days=1))) == [
        "FUTURE_INVOICE_DATE"
    ]


def test_today_is_allowed(validate, make_invoice):
    # The rule is <=, not <
    assert validate(make_invoice(invoice_date=TODAY)) == []


def test_unsupported_currency(validate, make_invoice):
    assert validate(make_invoice(currency="XYZ")) == ["INVALID_CURRENCY"]


@pytest.mark.parametrize("currency", ["EUR", "USD", "GBP"])
def test_supported_currencies_are_accepted(validate, make_invoice, currency):
    """The other half of the rule.

    Added after a deliberate regression check: removing GBP from
    SUPPORTED_CURRENCIES passed the entire suite, because every currency test
    only asserted that bad values are *rejected*. Testing what a rule forbids
    says nothing about what it permits.
    """
    assert validate(make_invoice(currency=currency)) == []


def test_currency_is_case_sensitive(validate, make_invoice):
    # Normalising input casing is Phase 18's job, not a rule's
    assert validate(make_invoice(currency="eur")) == ["INVALID_CURRENCY"]


@pytest.mark.parametrize("field", ["subtotal", "tax", "total"])
def test_negative_amounts(validate, make_invoice, field):
    amounts = {"subtotal": Decimal("0"), "tax": Decimal("0"), "total": Decimal("0")}
    amounts[field] = Decimal("-1")
    data = make_invoice(**amounts)
    assert "NEGATIVE_AMOUNT" in validate(data)


def test_zero_amounts_are_allowed(validate, make_invoice):
    # The rule is >=, not >
    data = make_invoice(
        subtotal=Decimal("0"), tax=Decimal("0"), total=Decimal("0")
    )
    assert validate(data) == []


def test_every_broken_rule_is_reported_at_once(validate, make_invoice):
    """Phase 4: a client should learn everything wrong in one round trip."""
    data = make_invoice(
        subtotal=Decimal("-5"), tax=Decimal("-5"), total=Decimal("9999"),
        currency="XYZ", invoice_date=TODAY + timedelta(days=365),
    )
    assert validate(data) == [
        "FUTURE_INVOICE_DATE",
        "INVALID_CURRENCY",
        "NEGATIVE_AMOUNT",
        "NEGATIVE_AMOUNT",
        "TOTAL_MISMATCH",
    ]


def test_decimal_arithmetic_is_exact(validate, make_invoice):
    """Phase 2's Decimal choice, pinned.

    With float columns this invoice would be rejected: 0.1 + 0.2 == 0.3 is
    False in binary floating point.
    """
    data = make_invoice(
        subtotal=Decimal("0.10"), tax=Decimal("0.20"), total=Decimal("0.30")
    )
    assert validate(data) == []
    assert 0.1 + 0.2 != 0.3  # the same sum, done the wrong way
