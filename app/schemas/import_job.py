from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field


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


class ImportErrorRead(BaseModel):
    """One thing that went wrong, as the API returns it.

    scope is what actually distinguishes the two shapes: a "row" error always
    has a row_number, an "invoice" error never does (there is no single row to
    point at). invoice_number/vendor do NOT reliably tell the two apart --
    Phase 19 reads a row's identity cells before anything else can fail, so a
    row-scoped error is very often stamped with the invoice_number/vendor it
    belongs to as well. That is deliberate (it lets a failed row be attributed
    to its invoice), not an inconsistency to code around.

    summary is not a column -- it is rendered here, once, from the stored
    fields. The playbook's own examples are two shapes:

        Row 12          -> missing vendor
        Invoice INV-1008 -> duplicate invoice

    Keeping code/field/message as the structured part (matching every other
    error surface in this API) and adding summary as a rendered convenience
    means a UI can show summary directly while software still filters on code
    -- rather than choosing one audience over the other.
    """

    model_config = ConfigDict(from_attributes=True)

    scope: str
    row_number: int | None
    invoice_number: str | None
    vendor: str | None
    code: str
    field: str | None
    message: str

    @computed_field
    @property
    def summary(self) -> str:
        if self.scope == "row":
            return f"Row {self.row_number} → {self.message}"
        return f"Invoice {self.invoice_number} → {self.message}"


class ImportErrorList(BaseModel):
    """A page of an import's errors.

    total is the count across the whole import, not just this page, so a
    client can tell "50 of 943" from "50 of 50" without a second request.
    """

    total: int
    limit: int
    offset: int
    errors: list[ImportErrorRead]
