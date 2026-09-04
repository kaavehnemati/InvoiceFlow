from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Invoice(Base):
    """The invoices table.

    Not to be confused with the Pydantic models in app/schemas/invoice.py.
    Those describe what crosses the API boundary; this describes what is stored
    in PostgreSQL. They happen to carry similar fields today, and they are free
    to diverge — a column can exist without being exposed, and a response field
    can be computed rather than stored.

    Money uses NUMERIC(12, 2): exact base-10 arithmetic, two decimal places,
    up to 9,999,999,999.99. A binary float column would reintroduce exactly the
    drift that Decimal was chosen to avoid.
    """

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(100))
    vendor: Mapped[str] = mapped_column(String(255))
    invoice_date: Mapped[date]
    currency: Mapped[str] = mapped_column(String(3))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # onupdate fires on UPDATE only, so the insert must set this explicitly.
    # Nothing updates an invoice yet — Phase 39's approve/reject is the first
    # thing that will, and this column is what will record it.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        onupdate=lambda: datetime.now(timezone.utc),
    )
