from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ImportJob(Base):
    """A record that a file was uploaded.

    Four columns, not the eleven in the domain model. storage_key arrives with
    S3 in Phase 31, the row counts with the import report in Phase 20, and
    started_at / completed_at when processing becomes asynchronous in Phase 32.
    A column nothing writes is a column nobody can trust, and migrations made
    adding them cheap.

    The id is a prefixed string rather than an integer: imp_a7f3c2e1 is the
    same value in the database, in the API, in a log line and in a support
    ticket, with nothing to strip or reassemble at the boundary.
    """

    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    # COMPLETED means processing ran to the end, not that everything worked --
    # the counts below carry the outcome. FAILED means processing itself broke.
    # PARTIALLY_COMPLETED waits for Phase 32, where an async worker can
    # genuinely stop halfway.
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Row-level and invoice-level counts answer different questions: 57 bad
    # rows might be 57 broken invoices, or one invoice with 57 lines.
    #
    #   total_rows     = valid_rows + invalid_rows        (blank rows excluded)
    #   invoices_found = created + failed + duplicates
    total_rows: Mapped[int] = mapped_column(default=0, server_default="0")
    valid_rows: Mapped[int] = mapped_column(default=0, server_default="0")
    invalid_rows: Mapped[int] = mapped_column(default=0, server_default="0")
    invoices_found: Mapped[int] = mapped_column(default=0, server_default="0")
    invoices_created: Mapped[int] = mapped_column(default=0, server_default="0")
    invoices_failed: Mapped[int] = mapped_column(default=0, server_default="0")
    duplicate_invoices: Mapped[int] = mapped_column(default=0, server_default="0")

    errors: Mapped[list["ImportError"]] = relationship(
        back_populates="import_job",
        cascade="all, delete-orphan",
        order_by="ImportError.id",
        lazy="selectin",
    )


class ImportError(Base):
    """One thing wrong with one row, or with one invoice.

    Persisted rather than recomputed: the uploaded file is discarded after
    processing, so an error not written down here is gone. Phase 21 reads these
    back to build its report, and Phase 31's S3 storage is what would eventually
    make recomputation possible.

    scope is what Phase 21's report distinguishes:

        Row 12          -> missing vendor
        Invoice INV-1008 -> duplicate invoice
    """

    __tablename__ = "import_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[str] = mapped_column(
        ForeignKey("import_jobs.id", ondelete="CASCADE"), index=True
    )

    scope: Mapped[str] = mapped_column(String(16))          # "row" or "invoice"
    row_number: Mapped[int | None] = mapped_column(nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(255), nullable=True)

    code: Mapped[str] = mapped_column(String(48))
    field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(String(500))

    import_job: Mapped["ImportJob"] = relationship(back_populates="errors")
