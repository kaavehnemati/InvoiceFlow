"""Accepting an import file, and checking that it is one.

Everything here is about *structure*: can this be opened, does it have the
sheet we expect, are the columns present. Nothing in this module looks at an
invoice. "I cannot read this spreadsheet" and "this invoice's totals do not add
up" are unrelated failures, and keeping them apart is what stops an import
report from being unreadable.

The column list and sheet name come from excel_template, so the file this
application hands out and the file it accepts are described by one definition.
"""
import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy.exc import DataError

from app.core.exceptions import (
    DuplicateInvoiceError,
    ImportFileError,
    InvoiceValidationError,
)
from app.models.import_job import ImportError as ImportErrorRow
from app.models.import_job import ImportJob
from app.repositories.import_job_repository import ImportJobRepository
from app.schemas.invoice import InvoiceCreate, InvoiceItemCreate
from app.services.excel_grouper import GroupedInvoice, group_rows
from app.services.excel_parser import parse_rows
from app.services.invoice_service import InvoiceService
from app.services.excel_template import (
    COLUMN_NAMES,
    SHEET_NAME,
    TEMPLATE_VERSION,
    VERSION_LABEL_CELL,
    VERSION_VALUE_CELL,
    INSTRUCTIONS_SHEET,
)

logger = logging.getLogger(__name__)


def _read_template_version(workbook) -> int | None:
    """Read the version Phase 16 wrote, if this file has one.

    A hand-built workbook with the right columns has no version cell and is
    perfectly valid, so absence is not an error -- it just means there is no
    hint to offer if something else goes wrong.
    """
    if INSTRUCTIONS_SHEET not in workbook.sheetnames:
        return None
    sheet = workbook[INSTRUCTIONS_SHEET]
    if sheet[VERSION_LABEL_CELL].value != "template_version":
        return None
    value = sheet[VERSION_VALUE_CELL].value
    return value if isinstance(value, int) else None


def validate_workbook_structure(filename: str, content: bytes) -> list[dict]:
    """Check that this file is a usable import workbook.

    Returns one issue per problem, or an empty list. Raises nothing, so Phase
    32's worker can call it with no request to fail -- the same shape as
    InvoiceService.validate().

    The checks stop at the first failure rather than accumulating. Unlike
    business rules, where reporting everything at once saves round trips, these
    are sequentially dependent: there is nothing to say about the columns of a
    file that is not a workbook.
    """
    if not filename or not filename.lower().endswith(".xlsx"):
        return [
            {
                "code": "INVALID_FILE_TYPE",
                "field": "file",
                "message": f"expected a .xlsx file, got {filename or 'no filename'}",
            }
        ]

    if not content:
        return [
            {"code": "EMPTY_FILE", "field": "file", "message": "the file is empty"}
        ]

    try:
        workbook = load_workbook(BytesIO(content), read_only=False, data_only=True)
    except Exception:
        # openpyxl raises a variety of types for a file that is not a workbook
        # -- zipfile.BadZipFile, KeyError, ValueError -- and the distinction is
        # of no use to whoever uploaded it.
        return [
            {
                "code": "UNREADABLE_WORKBOOK",
                "field": "file",
                "message": (
                    "the file could not be opened as an .xlsx workbook. It may be "
                    "corrupt, or saved in an older Excel format."
                ),
            }
        ]

    version = _read_template_version(workbook)

    if SHEET_NAME not in workbook.sheetnames:
        return [
            {
                "code": "WORKSHEET_MISSING",
                "field": "file",
                "message": (
                    f"the workbook has no sheet named '{SHEET_NAME}'. "
                    f"Found: {', '.join(workbook.sheetnames)}."
                ),
            }
        ]

    sheet = workbook[SHEET_NAME]
    header = [cell.value for cell in sheet[1]] if sheet.max_row else []
    missing = [name for name in COLUMN_NAMES if name not in header]

    if missing:
        message = f"missing required column(s): {', '.join(missing)}"
        # The version is only worth mentioning here. A file whose columns are
        # right imports fine whatever version it claims, so raising it then
        # would be noise; a file whose columns are wrong and which came from an
        # older template has an explanation worth offering.
        if version is not None and version != TEMPLATE_VERSION:
            message += (
                f". This file was made from template v{version}; "
                f"the current template is v{TEMPLATE_VERSION}."
            )
        return [{"code": "MISSING_COLUMNS", "field": "file", "message": message}]

    if sheet.max_row < 2:
        return [
            {
                "code": "NO_DATA_ROWS",
                "field": "file",
                "message": (
                    f"the '{SHEET_NAME}' sheet has a header row but no data rows"
                ),
            }
        ]

    return []


def to_invoice_create(grouped: GroupedInvoice) -> InvoiceCreate:
    """A grouped spreadsheet invoice, as the API's own request model.

    This mapping is the only new logic in the import path. Everything that
    decides whether the invoice is acceptable is borrowed from
    InvoiceService -- the same object a JSON request goes through.

    The spreadsheet says declared_subtotal and item; the domain says subtotal
    and description. Phase 16 documented those mappings; this is where they
    are applied.
    """
    return InvoiceCreate(
        invoice_number=grouped.invoice_number,
        vendor=grouped.vendor,
        invoice_date=grouped.invoice_date,
        currency=grouped.currency,
        subtotal=grouped.declared_subtotal,
        tax=grouped.declared_tax,
        total=grouped.declared_total,
        items=[
            InvoiceItemCreate(
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
            )
            for item in grouped.items
        ],
    )


class ImportService:
    """Turns an uploaded file into invoices, and reports what happened."""

    def __init__(
        self, repository: ImportJobRepository, invoice_service: InvoiceService
    ):
        self.repository = repository
        self.invoice_service = invoice_service

    def create_from_upload(self, filename: str, content: bytes) -> ImportJob:
        """Check the file's structure and record that it arrived.

        The bytes are not kept. Phases 18-21 process in this same request, so
        there is nothing to store yet; Phase 31 introduces S3 with its own
        reason for existing.

        Raises:
            ImportFileError: the file is not a usable import workbook.
        """
        issues = validate_workbook_structure(filename, content)
        if issues:
            logger.info(
                "import_rejected",
                extra={
                    "context": {
                        "filename": filename,
                        "issue_codes": [i["code"] for i in issues],
                    }
                },
            )
            raise ImportFileError(issues)

        job = ImportJob(
            id=f"imp_{uuid.uuid4().hex[:12]}",
            filename=filename,
            status="UPLOADED",
            created_at=datetime.now(timezone.utc),
        )
        created = self.repository.create(job)
        logger.info(
            "import_uploaded",
            extra={
                "context": {"import_id": created.id, "filename": created.filename}
            },
        )

        self._process(created, content)
        return created

    def _process(self, job: ImportJob, content: bytes) -> None:
        """Parse, group, validate and store every invoice in the file.

        Each invoice is created through InvoiceService.create() -- the same
        call a JSON request makes. Not similar rules: the same object, raising
        the same domain exceptions. That is the whole point of the layering,
        and tests/test_import_report.py has a test that fails the moment
        anyone reimplements a rule here.

        Each invoice commits on its own, so one bad invoice does not cost the
        good ones. That currently falls out of InvoiceRepository.create()
        committing rather than from anyone deciding it, which is exactly what
        Phase 22 exists to make deliberate.
        """
        rows, row_errors = parse_rows(content)
        invoices, invoice_errors = group_rows(rows, row_errors)

        stored_errors: list[ImportErrorRow] = [
            ImportErrorRow(
                import_id=job.id,
                scope="row",
                row_number=error.row_number,
                invoice_number=error.invoice_number or None,
                vendor=error.vendor or None,
                code=error.code,
                field=error.field,
                message=error.message[:500],
            )
            for error in row_errors
        ]

        failed = 0
        duplicates = 0

        for error in invoice_errors:
            failed += 1
            stored_errors.append(
                ImportErrorRow(
                    import_id=job.id,
                    scope="invoice",
                    row_number=None,
                    invoice_number=error.invoice_number or None,
                    vendor=error.vendor or None,
                    code=error.code,
                    field=error.field,
                    message=error.message[:500],
                )
            )

        created_count = 0
        for grouped in invoices:
            try:
                self.invoice_service.create(to_invoice_create(grouped))
                created_count += 1
            except InvoiceValidationError as exc:
                failed += 1
                for issue in exc.issues:
                    stored_errors.append(
                        ImportErrorRow(
                            import_id=job.id,
                            scope="invoice",
                            row_number=None,
                            invoice_number=grouped.invoice_number,
                            vendor=grouped.vendor,
                            code=issue["code"],
                            field=issue.get("field"),
                            message=str(issue["message"])[:500],
                        )
                    )
            except DuplicateInvoiceError as exc:
                duplicates += 1
                stored_errors.append(
                    ImportErrorRow(
                        import_id=job.id,
                        scope="invoice",
                        row_number=None,
                        invoice_number=grouped.invoice_number,
                        vendor=grouped.vendor,
                        code="DUPLICATE_INVOICE",
                        field="invoice_number",
                        message=str(exc)[:500],
                    )
                )
            except DataError:
                # A DB-level failure -- e.g. an amount too large for
                # NUMERIC(12,2) -- leaves the session unusable until it is
                # explicitly rolled back. Without this, every invoice after
                # this one in the same import would also fail, the whole
                # import would abort before its counts and errors were ever
                # written, and the client would see a bare 422 for the entire
                # upload instead of a completed report. Verified directly:
                # rollback() recovers the session, and the next create() on it
                # succeeds normally.
                #
                # Same exception, same code, as a single JSON request would
                # get from Phase 12's handler -- one failure produces one
                # meaning, whether it arrives alone or as one row in a much
                # larger file.
                self.repository.session.rollback()
                failed += 1
                stored_errors.append(
                    ImportErrorRow(
                        import_id=job.id,
                        scope="invoice",
                        row_number=None,
                        invoice_number=grouped.invoice_number,
                        vendor=grouped.vendor,
                        code="AMOUNT_OUT_OF_RANGE",
                        field=None,
                        message=(
                            "an amount is outside the range this system can store"
                        ),
                    )
                )

        invalid_rows = len({error.row_number for error in row_errors})

        job.total_rows = len(rows) + invalid_rows
        job.valid_rows = len(rows)
        job.invalid_rows = invalid_rows
        job.invoices_found = len(invoices) + len(invoice_errors)
        job.invoices_created = created_count
        job.invoices_failed = failed
        job.duplicate_invoices = duplicates
        job.status = "COMPLETED"

        self.repository.save_with_errors(job, stored_errors)

        logger.info(
            "import_processed",
            extra={
                "context": {
                    "import_id": job.id,
                    "total_rows": job.total_rows,
                    "invoices_created": job.invoices_created,
                    "invoices_failed": job.invoices_failed,
                    "duplicate_invoices": job.duplicate_invoices,
                }
            },
        )
