"""Service tests: business behavior, including the rules that need the database.

These raise and catch domain exceptions only. Nothing here imports FastAPI --
which is Phase 12's Definition of Done, enforced by test_architecture.py.
"""
from decimal import Decimal

import pytest

from app.core.exceptions import DuplicateInvoiceError, InvoiceValidationError
from app.models.invoice import Invoice


def test_create_valid_invoice(service, make_invoice):
    invoice = service.create(make_invoice())

    assert isinstance(invoice, Invoice)  # not a tuple -- Phase 12 retired that
    assert invoice.id is not None
    assert invoice.status == "VALID"
    assert invoice.created_at == invoice.updated_at


def test_create_rejects_invalid_invoice(service, make_invoice):
    with pytest.raises(InvoiceValidationError) as exc:
        service.create(make_invoice(currency="XYZ"))

    assert [i["code"] for i in exc.value.issues] == ["INVALID_CURRENCY"]


def test_duplicate_invoice(service, make_invoice):
    service.create(make_invoice(invoice_number="DUP-1"))

    with pytest.raises(DuplicateInvoiceError) as exc:
        service.create(make_invoice(invoice_number="DUP-1"))

    assert exc.value.invoice_number == "DUP-1"
    assert exc.value.vendor == "ABC GmbH"


def test_same_number_different_vendor_is_not_a_duplicate(service, make_invoice):
    service.create(make_invoice(invoice_number="SHARED", vendor="ABC GmbH"))
    other = service.create(make_invoice(invoice_number="SHARED", vendor="Other Ltd"))

    assert other.id is not None


def test_validation_beats_duplicate(service, make_invoice):
    """Phase 12's precedence decision.

    An invoice that is both malformed and a duplicate reports the malformation.
    A duplicate of a broken invoice is not a conflict, it is just wrong.
    """
    service.create(make_invoice(invoice_number="BOTH"))

    with pytest.raises(InvoiceValidationError):
        service.create(make_invoice(invoice_number="BOTH", currency="XYZ"))


def test_rejected_invoice_is_not_stored(service, repository, make_invoice):
    with pytest.raises(InvoiceValidationError):
        service.create(make_invoice(invoice_number="NOPE", currency="XYZ"))

    assert repository.find_by_vendor_and_invoice_number("ABC GmbH", "NOPE") is None


def test_validate_touches_no_database(make_invoice):
    """Phase 12 made validate() pure; a None repository proves it."""
    from app.services.invoice_service import InvoiceService

    assert InvoiceService(repository=None).validate(make_invoice()) == []


@pytest.mark.xfail(
    reason="Known gap: NUMERIC(12,2) rounds after validation has run, so an "
    "invoice can pass TOTAL_MISMATCH and be stored inconsistently. "
    "Documented in README under 'The rounding gap, in detail'.",
    strict=True,
)
def test_scale_rounding_preserves_totals(service, db_session, make_invoice):
    """0.005 + 0.005 == 0.010 passes validation, then rounds to 0.01 + 0.01 = 0.01."""
    invoice = service.create(
        make_invoice(
            invoice_number="ROUND-1",
            subtotal=Decimal("0.005"), tax=Decimal("0.005"), total=Decimal("0.010"),
        )
    )
    db_session.refresh(invoice)
    assert invoice.subtotal + invoice.tax == invoice.total
