from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ImportJobRead(BaseModel):
    """An import job as the API returns it.

    The playbook's example shows id, filename and status. created_at is added
    for consistency with InvoiceRead, and because "when did this arrive" is the
    first question anyone asks about an import.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    status: str
    created_at: datetime

    # Row-level and invoice-level counts answer different questions.
    #   total_rows     = valid_rows + invalid_rows
    #   invoices_found = created + failed + duplicates
    total_rows: int
    valid_rows: int
    invalid_rows: int
    invoices_found: int
    invoices_created: int
    invoices_failed: int
    duplicate_invoices: int
