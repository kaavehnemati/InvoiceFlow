from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class InvoiceCreate(BaseModel):
    """The shape of an invoice a client is allowed to send.

    This describes structure only: which fields are required and what type each
    one is. Whether the numbers make sense together is a separate question, and
    Phase 4 answers it.

    Amounts use Decimal rather than float because binary floats cannot represent
    values like 0.10 exactly, so their arithmetic drifts. On money that drift
    becomes a cent that does not reconcile.
    """

    invoice_number: str
    vendor: str
    invoice_date: date
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal


class InvoiceRead(BaseModel):
    """The shape of an invoice the API returns.

    Deliberately a separate class rather than a subclass of InvoiceCreate. The
    two describe opposite directions of travel and are free to diverge: a field
    the client sends need not be a field the API echoes back, and vice versa.
    `id`, `status` and `created_at` are assigned by the server, so a client can
    never supply them.
    """

    # Build from an object's attributes, not just a dict, so a route can return
    # a SQLAlchemy Invoice row directly and have it read field by field.
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_number: str
    vendor: str
    invoice_date: date
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    status: str
    created_at: datetime
    updated_at: datetime
