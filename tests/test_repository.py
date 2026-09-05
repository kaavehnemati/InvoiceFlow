"""Integration tests: real SQL against a real PostgreSQL, inside a rolled-back
transaction."""
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.invoice import Invoice


def build(**overrides) -> Invoice:
    now = datetime.now(timezone.utc)
    defaults = dict(
        invoice_number="REPO-1", vendor="ABC GmbH", invoice_date=date.today(),
        currency="EUR", subtotal=Decimal("1000.00"), tax=Decimal("190.00"),
        total=Decimal("1190.00"), status="VALID", created_at=now, updated_at=now,
    )
    return Invoice(**{**defaults, **overrides})


def test_create_assigns_an_id(repository):
    invoice = repository.create(build())
    assert invoice.id is not None


def test_get_by_id(repository):
    created = repository.create(build())
    assert repository.get_by_id(created.id).invoice_number == "REPO-1"


def test_get_by_id_returns_none_when_missing(repository):
    assert repository.get_by_id(999_999) is None


def test_list_all_is_ordered_by_id(repository):
    for n in ("A", "B", "C"):
        repository.create(build(invoice_number=n))

    listed = repository.list_all()
    ids = [i.id for i in listed]
    assert ids == sorted(ids)
    assert {"A", "B", "C"} <= {i.invoice_number for i in listed}


def test_find_by_vendor_and_invoice_number(repository):
    repository.create(build(invoice_number="FIND-1", vendor="Acme"))

    assert repository.find_by_vendor_and_invoice_number("Acme", "FIND-1") is not None
    assert repository.find_by_vendor_and_invoice_number("Acme", "NOPE") is None
    # vendor is part of the key
    assert repository.find_by_vendor_and_invoice_number("Other", "FIND-1") is None


def test_decimal_round_trips_through_postgres(repository):
    invoice = repository.create(
        build(subtotal=Decimal("0.10"), tax=Decimal("0.20"), total=Decimal("0.30"))
    )
    reloaded = repository.get_by_id(invoice.id)

    assert isinstance(reloaded.subtotal, Decimal)
    assert reloaded.subtotal + reloaded.tax == reloaded.total


def test_repository_stores_an_invoice_that_breaks_every_rule(repository):
    """Phase 8's boundary, pinned.

    The repository handles persistence only. It does not decide whether an
    invoice is any good, and it must keep not deciding -- that is what lets
    Phase 20's importer and Phase 39's review workflow reuse it.
    """
    nonsense = repository.create(
        build(
            invoice_number="NONSENSE",
            invoice_date=date(2099, 12, 31),      # future
            currency="XYZ",                       # unsupported
            subtotal=Decimal("-5.00"),            # negative
            tax=Decimal("-5.00"),
            total=Decimal("9999.00"),             # does not add up
        )
    )

    assert nonsense.id is not None
    assert nonsense.subtotal + nonsense.tax != nonsense.total
