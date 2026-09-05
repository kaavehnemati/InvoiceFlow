class InvoiceFlowError(Exception):
    """Base for every domain error this application raises.

    These are plain Python exceptions. None of them mentions a status code,
    because a status code is one particular transport's opinion about an error
    rather than a property of the error itself. "This invoice already exists"
    is true whether it was submitted over HTTP, read from a spreadsheet, or
    extracted from a PDF; only the HTTP case cares that the answer is 409.

    Each subclass carries the data a caller needs rather than a pre-rendered
    message, so the HTTP layer can build a response body, a bulk importer can
    build a report row, and Phase 13 can log structured fields -- all from the
    same exception.
    """


class InvoiceNotFoundError(InvoiceFlowError):
    def __init__(self, invoice_id: int):
        self.invoice_id = invoice_id
        super().__init__(f"invoice {invoice_id} not found")


class DuplicateInvoiceError(InvoiceFlowError):
    def __init__(self, vendor: str, invoice_number: str):
        self.vendor = vendor
        self.invoice_number = invoice_number
        super().__init__(
            f"invoice {invoice_number} already exists for vendor {vendor}"
        )


class InvoiceValidationError(InvoiceFlowError):
    def __init__(self, issues: list[dict]):
        self.issues = issues
        super().__init__(f"{len(issues)} validation issue(s)")


class ImportFileError(InvoiceFlowError):
    """The uploaded file is not a usable import workbook.

    Structural, not business: this says nothing about the invoices inside.
    """

    def __init__(self, issues: list[dict]):
        self.issues = issues
        super().__init__(f"{len(issues)} structural issue(s)")


class ImportJobNotFoundError(InvoiceFlowError):
    def __init__(self, import_id: str):
        self.import_id = import_id
        super().__init__(f"import {import_id} not found")
