from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

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
    # Plain string, as Invoice.status was in Phase 3. Only UPLOADED exists so
    # far; the other five statuses arrive when something can produce them.
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
