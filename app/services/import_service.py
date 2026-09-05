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

from app.core.exceptions import ImportFileError
from app.models.import_job import ImportJob
from app.repositories.import_job_repository import ImportJobRepository
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


class ImportService:
    """Turns an uploaded file into an ImportJob, or refuses it."""

    def __init__(self, repository: ImportJobRepository):
        self.repository = repository

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
        return created
