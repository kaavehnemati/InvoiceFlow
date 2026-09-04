from datetime import datetime, timezone

from app.models.invoice import Invoice
from app.repositories.invoice_repository import InvoiceRepository
from app.schemas.invoice import InvoiceCreate

SUPPORTED_CURRENCIES = {"EUR", "USD", "GBP"}


class InvoiceService:
    """Business behavior for invoices.

    This is where the question "should we accept this invoice?" is answered.
    The router above it knows about HTTP and nothing else; the repository below
    it knows about storage and nothing else.

    Note what this module does not import: FastAPI. Nothing here knows what a
    status code is, which is what lets the rules be exercised without a running
    server -- and what will let the Excel importer in Phase 20 and the document
    extractor in Phase 38 apply the same rules to invoices that never arrived
    over HTTP.
    """

    def __init__(self, repository: InvoiceRepository):
        self.repository = repository

    def create(self, data: InvoiceCreate) -> tuple[Invoice | None, list[dict]]:
        """Validate and store an invoice.

        Returns (invoice, []) on success, or (None, issues) if any rule was
        broken. The caller decides what that means -- the router turns issues
        into a 422; a bulk importer would collect them into a report.

        Returning a tuple rather than raising is deliberate: an exception would
        have to be either FastAPI's HTTPException, which would weld this class
        to the web framework, or a domain exception, which Phase 12 introduces.
        """
        issues = self.validate(data)
        if issues:
            return None, issues

        now = datetime.now(timezone.utc)
        invoice = Invoice(
            **data.model_dump(),
            # Deciding an invoice is VALID is a business judgement, so it is
            # made here rather than in the router.
            status="VALID",
            created_at=now,
            updated_at=now,
        )
        return self.repository.create(invoice), []

    def validate(self, data: InvoiceCreate) -> list[dict]:
        """Check an invoice against every business rule.

        InvoiceCreate already guarantees the invoice has the right *shape*.
        These rules decide whether it makes sense: an invoice whose fields are
        all the correct type can still claim that 1000 + 190 = 1300.

        Returns one issue per broken rule, or an empty list if the invoice is
        valid. Every rule is checked rather than stopping at the first failure,
        so a caller learns everything that is wrong in one pass.
        """
        issues = []

        for field in ("subtotal", "tax", "total"):
            if getattr(data, field) < 0:
                issues.append(
                    {
                        "code": "NEGATIVE_AMOUNT",
                        "field": field,
                        "message": f"{field} must not be negative",
                    }
                )

        if data.subtotal + data.tax != data.total:
            issues.append(
                {
                    "code": "TOTAL_MISMATCH",
                    "field": "total",
                    "message": (
                        f"subtotal ({data.subtotal}) + tax ({data.tax}) "
                        f"must equal total ({data.total})"
                    ),
                }
            )

        today = datetime.now(timezone.utc).date()
        if data.invoice_date > today:
            issues.append(
                {
                    "code": "FUTURE_INVOICE_DATE",
                    "field": "invoice_date",
                    "message": f"invoice_date {data.invoice_date} is in the future",
                }
            )

        if data.currency not in SUPPORTED_CURRENCIES:
            issues.append(
                {
                    "code": "INVALID_CURRENCY",
                    "field": "currency",
                    "message": (
                        f"currency must be one of "
                        f"{', '.join(sorted(SUPPORTED_CURRENCIES))}"
                    ),
                }
            )

        # The one rule that cannot be answered from the invoice alone: it needs
        # to know what is already stored. This is why the rules had to leave the
        # router -- a check like this needs the repository.
        if self.repository.find_by_vendor_and_invoice_number(
            data.vendor, data.invoice_number
        ):
            issues.append(
                {
                    "code": "DUPLICATE_INVOICE",
                    "field": "invoice_number",
                    "message": (
                        f"invoice {data.invoice_number} already exists "
                        f"for vendor {data.vendor}"
                    ),
                }
            )

        return issues
