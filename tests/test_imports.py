"""Upload and structural validation.

Nothing here checks an invoice. A file full of invoices that Phase 20 will
reject is still a structurally valid file, and this phase says so.
"""
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.models.import_job import ImportJob
from app.services.excel_template import (
    COLUMN_NAMES,
    INSTRUCTIONS_SHEET,
    SHEET_NAME,
    VERSION_LABEL_CELL,
    VERSION_VALUE_CELL,
    build_template_workbook,
)
from app.services.import_service import validate_workbook_structure

# One valid data row, matching the template's column order.
VALID_ROW = [
    "INV-2026-1001", "ABC GmbH", "2026-01-15", "Consulting",
    2, 100.00, 19, "EUR", 250.00, 47.50, 297.50,
]


def to_bytes(workbook: Workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def filled_template(rows=(VALID_ROW,)) -> bytes:
    """The template this application publishes, with data in it."""
    workbook = load_workbook(BytesIO(build_template_workbook()))
    for row in rows:
        workbook[SHEET_NAME].append(row)
    return to_bytes(workbook)


def codes(issues) -> list[str]:
    return [i["code"] for i in issues]


def upload(client, content: bytes, filename="invoices.xlsx"):
    return client.post(
        "/imports",
        files={
            "file": (
                filename,
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


# ----------------------------------------------------------- the contract loop


def test_the_published_template_filled_in_is_accepted(client):
    """The most important test here.

    Phase 16 publishes a template; this phase validates uploads. If those two
    ever describe different files, this fails -- which is the whole reason the
    column list is one constant rather than two.
    """
    response = upload(client, filled_template())

    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("imp_")
    assert body["status"] == "UPLOADED"
    assert body["filename"] == "invoices.xlsx"


def test_a_filled_template_passes_structural_validation_directly():
    assert validate_workbook_structure("invoices.xlsx", filled_template()) == []


# ------------------------------------------------------- each structural failure


def test_wrong_extension():
    issues = validate_workbook_structure("invoices.txt", b"whatever")
    assert codes(issues) == ["INVALID_FILE_TYPE"]
    assert ".xlsx" in issues[0]["message"]


def test_empty_file():
    issues = validate_workbook_structure("invoices.xlsx", b"")
    assert codes(issues) == ["EMPTY_FILE"]


def test_not_actually_a_workbook():
    """An .xlsx name on something that is not a zip archive."""
    issues = validate_workbook_structure("invoices.xlsx", b"this is not a spreadsheet")
    assert codes(issues) == ["UNREADABLE_WORKBOOK"]
    assert "corrupt" in issues[0]["message"]


def test_missing_worksheet():
    workbook = Workbook()
    workbook.active.title = "Sheet1"
    workbook.active.append(list(COLUMN_NAMES))

    issues = validate_workbook_structure("invoices.xlsx", to_bytes(workbook))
    assert codes(issues) == ["WORKSHEET_MISSING"]
    assert SHEET_NAME in issues[0]["message"]
    assert "Sheet1" in issues[0]["message"]


def test_missing_columns_names_them():
    workbook = Workbook()
    workbook.active.title = SHEET_NAME
    workbook.active.append([c for c in COLUMN_NAMES if c not in ("vendor", "currency")])
    workbook.active.append(["x"] * 9)

    issues = validate_workbook_structure("invoices.xlsx", to_bytes(workbook))
    assert codes(issues) == ["MISSING_COLUMNS"]
    assert "vendor" in issues[0]["message"]
    assert "currency" in issues[0]["message"]


def test_headers_but_no_data_rows():
    """The template as downloaded, unfilled."""
    issues = validate_workbook_structure("invoices.xlsx", build_template_workbook())
    assert codes(issues) == ["NO_DATA_ROWS"]


# ------------------------------------------------------------- the version hint


def test_version_explains_a_column_failure():
    workbook = load_workbook(BytesIO(build_template_workbook()))
    workbook[INSTRUCTIONS_SHEET][VERSION_VALUE_CELL] = 0  # an older template
    sheet = workbook[SHEET_NAME]
    sheet.delete_cols(2)  # drop vendor
    sheet.append(["x"] * 10)

    issues = validate_workbook_structure("invoices.xlsx", to_bytes(workbook))
    assert codes(issues) == ["MISSING_COLUMNS"]
    assert "template v0" in issues[0]["message"]


def test_version_is_not_mentioned_when_columns_are_fine():
    """A correct file imports whatever version it claims."""
    workbook = load_workbook(BytesIO(build_template_workbook()))
    workbook[INSTRUCTIONS_SHEET][VERSION_VALUE_CELL] = 0
    workbook[SHEET_NAME].append(VALID_ROW)

    assert validate_workbook_structure("invoices.xlsx", to_bytes(workbook)) == []


def test_a_workbook_with_no_version_cell_is_fine():
    """Hand-built files have no Instructions sheet. Columns are what matter."""
    workbook = Workbook()
    workbook.active.title = SHEET_NAME
    workbook.active.append(list(COLUMN_NAMES))
    workbook.active.append(VALID_ROW)

    assert validate_workbook_structure("invoices.xlsx", to_bytes(workbook)) == []


# ------------------------------------------------------------------- the API


def test_rejected_upload_returns_422_with_issues(client):
    response = upload(client, b"not a workbook", filename="invoices.xlsx")

    assert response.status_code == 422
    assert codes(response.json()["detail"]) == ["UNREADABLE_WORKBOOK"]


def test_rejected_upload_creates_no_job(client, db_session):
    upload(client, b"", filename="invoices.xlsx")
    assert db_session.query(ImportJob).count() == 0


def test_accepted_upload_is_persisted(client, db_session):
    import_id = upload(client, filled_template()).json()["id"]

    job = db_session.get(ImportJob, import_id)
    assert job is not None
    assert job.status == "UPLOADED"
    assert job.created_at is not None


def test_structure_is_not_business_validation(client, db_session):
    """A file full of invoices Phase 20 will reject is still structurally fine.

    Negative quantity, a currency that does not exist, a date in the far
    future, totals that do not add up -- every one of these is a business rule,
    and this phase does not have an opinion about any of them.
    """
    nonsense = [
        "INV-BAD", "ABC GmbH", "2099-12-31", "Item",
        -5, -100.00, 900, "XYZ", 1.00, 1.00, 99999.00,
    ]
    response = upload(client, filled_template(rows=(nonsense,)))

    assert response.status_code == 201
    # ...and no invoice was created, because nothing parsed the rows
    from app.models.invoice import Invoice

    assert db_session.query(Invoice).count() == 0


def test_upload_with_no_filename_is_rejected(client):
    response = client.post("/imports", files={"file": ("", b"data", "text/plain")})
    assert response.status_code == 422


def test_openapi_declares_a_file_upload(client):
    schema = client.get("/openapi.json").json()
    content = schema["paths"]["/imports"]["post"]["requestBody"]["content"]
    assert "multipart/form-data" in content
