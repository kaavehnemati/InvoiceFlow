from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice",
        # The database and the ORM agree that an item cannot outlive its
        # invoice: delete-orphan handles it in Python, ondelete="CASCADE" on
        # the foreign key handles it in SQL.
        cascade="all, delete-orphan",
        order_by="InvoiceItem.id",
        # Not the default lazy load. Serializing a list of invoices would
        # otherwise fire one query per invoice, and would fail outright on an
        # instance whose session has already closed. selectin fetches every
        # invoice's items in one additional query.
        lazy="selectin",
    )


class InvoiceItem(Base):
    """One line on an invoice.

    The three line_* amounts are derived from quantity, unit_price and
    tax_rate rather than supplied -- see derive_line_amounts() in the service.
    They are stored anyway: an invoice is a record of what was agreed, and
    recomputing it later from a tax rate that has since changed would quietly
    rewrite history.
    """

    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )

    description: Mapped[str] = mapped_column(String(500))
    # Quantities are not always whole: 2.5 hours, 0.75 kg.
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # A percentage, 0.00 to 100.00 -- so 19% is stored as 19, not 0.19.
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    invoice: Mapped["Invoice"] = relationship(back_populates="items")
