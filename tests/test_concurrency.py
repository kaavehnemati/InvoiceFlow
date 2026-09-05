"""The duplicate race, as an executable description of a known gap.

This test cannot use the rollback fixture. Reproducing the race needs two
independent connections that really commit, which is precisely what the
fixture exists to prevent -- so it manages its own connections and cleans up
after itself in a finally block.

It is deterministic rather than timing-dependent: both sessions are made to
check before either writes, which is the interleaving the code permits. It
does not sleep, race threads, or hope.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.invoice import Invoice
from app.repositories.invoice_repository import InvoiceRepository

VENDOR = "Race Test Ltd"
NUMBER = "RACE-XFAIL-1"


def build() -> Invoice:
    now = datetime.now(timezone.utc)
    return Invoice(
        invoice_number=NUMBER, vendor=VENDOR, invoice_date=date.today(),
        currency="EUR", subtotal=Decimal("10.00"), tax=Decimal("1.90"),
        total=Decimal("11.90"), status="VALID", created_at=now, updated_at=now,
    )


@pytest.mark.xfail(
    reason="Known gap: the duplicate check is check-then-insert with no unique "
    "constraint underneath, so two concurrent requests can both pass the check "
    "and both write. Documented in README under 'The duplicate race, in "
    "detail'. Fixing it needs a migration plus IntegrityError handling.",
    strict=True,
)
def test_concurrent_creates_cannot_both_succeed():
    try:
        with Session(engine) as a, Session(engine) as b:
            repo_a, repo_b = InvoiceRepository(a), InvoiceRepository(b)

            # Both check first -- the interleaving the current code allows.
            assert repo_a.find_by_vendor_and_invoice_number(VENDOR, NUMBER) is None
            assert repo_b.find_by_vendor_and_invoice_number(VENDOR, NUMBER) is None

            # Both then write, each believing the field is clear.
            repo_a.create(build())
            repo_b.create(build())

        with Session(engine) as check:
            stored = InvoiceRepository(check).session.query(Invoice).filter(
                Invoice.vendor == VENDOR, Invoice.invoice_number == NUMBER
            ).count()

        assert stored == 1, f"{stored} rows share vendor + invoice_number"
    finally:
        # These are real commits on the real database; clean them up.
        with Session(engine) as cleanup:
            cleanup.execute(
                delete(Invoice).where(
                    Invoice.vendor == VENDOR, Invoice.invoice_number == NUMBER
                )
            )
            cleanup.commit()
