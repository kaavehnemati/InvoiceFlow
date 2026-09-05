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
