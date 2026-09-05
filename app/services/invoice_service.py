import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.core.exceptions import DuplicateInvoiceError, InvoiceValidationError
from app.models.invoice import Invoice, InvoiceItem
from app.repositories.invoice_repository import InvoiceRepository
from app.schemas.invoice import InvoiceCreate, InvoiceItemCreate

logger = logging.getLogger(__name__)

SUPPORTED_CURRENCIES = {"EUR", "USD", "GBP"}

CENTS = Decimal("0.01")


def derive_line_amounts(item: InvoiceItemCreate) -> tuple[Decimal, Decimal, Decimal]:
    """Compute a line's three amounts from what the client actually sent.

    The playbook writes the tax rule as `line_tax = line_subtotal x tax_rate`,
    which cannot be meant literally: the neighbouring rule bounds tax_rate to
    0..100, so a rate of 19% is stored as 19 and multiplying by it directly
    would produce tax a hundred times too large. Hence the division.

    Each amount is rounded to cents as it is computed rather than at the end.
    That keeps the stored lines summing exactly to the stored invoice totals --
    if the rounding happened only on the total, the lines on the invoice would
    not add up to the invoice, which is the one thing this phase exists to
    make checkable.

    This function is the single definition of that arithmetic. validate() uses
    it to check the declared totals and create() uses it to build the rows, so
    the two cannot disagree.
    """
    line_subtotal = (item.quantity * item.unit_price).quantize(
        CENTS, rounding=ROUND_HALF_UP
    )
    line_tax = (line_subtotal * item.tax_rate / 100).quantize(
        CENTS, rounding=ROUND_HALF_UP
    )
    return line_subtotal, line_tax, line_subtotal + line_tax


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

    def create(self, data: InvoiceCreate) -> Invoice:
        """Validate and store an invoice.

        Returns the stored invoice, or raises a domain exception describing why
        it was refused. The exceptions are plain Python and mention no status
        codes, so this class stays usable by callers that have no HTTP request
        to fail -- the Excel importer in Phase 20, the document extractor in
        Phase 38.

        Raises:
            InvoiceValidationError: one or more business rules were broken.
            DuplicateInvoiceError: the invoice is fine, but already exists.
        """
        issues = self.validate(data)
        if issues:
            # INFO, not WARNING: a client sending something invalid and being
            # told so is a normal outcome, not a symptom of trouble. Reserving
            # the higher levels for things that need attention is what keeps
            # them meaningful.
            logger.info(
                "invoice_rejected",
                extra={
                    "context": {
                        "invoice_number": data.invoice_number,
                        "vendor": data.vendor,
                        "issue_codes": [i["code"] for i in issues],
                    }
                },
            )
            raise InvoiceValidationError(issues)

        # Checked after the rules, not among them: a duplicate of a malformed
        # invoice is not a conflict, it is just wrong. Only an otherwise-valid
        # invoice can meaningfully collide with one already stored.
        if self.repository.find_by_vendor_and_invoice_number(
            data.vendor, data.invoice_number
        ):
            logger.info(
                "duplicate_detected",
                extra={
                    "context": {
                        "invoice_number": data.invoice_number,
                        "vendor": data.vendor,
                    }
                },
            )
            raise DuplicateInvoiceError(data.vendor, data.invoice_number)

        now = datetime.now(timezone.utc)
        invoice = Invoice(
            **data.model_dump(exclude={"items"}),
            # Deciding an invoice is VALID is a business judgement, so it is
            # made here rather than in the router.
            status="VALID",
            created_at=now,
            updated_at=now,
        )

        # Appending to the relationship is enough: the cascade writes the items
        # with the invoice, in the same commit, so an invoice can never be
        # stored without the lines that justify its totals. Phase 22 makes that
        # boundary explicit rather than incidental.
        for item in data.items:
            line_subtotal, line_tax, line_total = derive_line_amounts(item)
            invoice.items.append(
                InvoiceItem(
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    tax_rate=item.tax_rate,
                    line_subtotal=line_subtotal,
                    line_tax=line_tax,
                    line_total=line_total,
                )
            )

        created = self.repository.create(invoice)
        logger.info(
            "invoice_created",
            extra={
                "context": {
                    "invoice_id": created.id,
                    "invoice_number": created.invoice_number,
                    "vendor": created.vendor,
                }
            },
        )
        return created

    def validate(self, data: InvoiceCreate) -> list[dict]:
        """Check an invoice against the business rules.

        InvoiceCreate already guarantees the invoice has the right *shape*.
        These rules decide whether it makes sense: an invoice whose fields are
        all the correct type can still claim that 1000 + 190 = 1300.

        Returns one issue per broken rule, or an empty list if the invoice is
        valid. Every rule is checked rather than stopping at the first failure,
        so a caller learns everything that is wrong in one pass.

        This method is pure: it touches no database and raises nothing, so it
        can be called on a spreadsheet row, an OCR result, or anything else
        invoice-shaped. Duplicate detection is deliberately not here -- it
        requires the database and belongs to create().
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

        issues.extend(self._validate_items(data))
        return issues

    def _validate_items(self, data: InvoiceCreate) -> list[dict]:
        """Check each line, then reconcile the declared totals against them.

        An invoice with no items is not an error -- it is still allowed to
        assert its own totals. But once it says what was bought, the header has
        to agree with the lines.
        """
        if not data.items:
            return []

        issues = []
        for index, item in enumerate(data.items):
            where = f"items[{index}]"

            if item.quantity <= 0:
                issues.append(
                    {
                        "code": "INVALID_QUANTITY",
                        "field": f"{where}.quantity",
                        "message": (
                            f"quantity must be greater than 0, got {item.quantity}"
                        ),
                    }
                )
            if item.unit_price < 0:
                issues.append(
                    {
                        "code": "NEGATIVE_AMOUNT",
                        "field": f"{where}.unit_price",
                        "message": "unit_price must not be negative",
                    }
                )
            if not (0 <= item.tax_rate <= 100):
                issues.append(
                    {
                        "code": "INVALID_TAX_RATE",
                        "field": f"{where}.tax_rate",
                        "message": (
                            f"tax_rate must be between 0 and 100, got {item.tax_rate}"
                        ),
                    }
                )

        # Reconciling against lines that are themselves invalid would only
        # produce noise on top of the real problem.
        if issues:
            return issues

        derived = [derive_line_amounts(item) for item in data.items]
        line_subtotal = sum((d[0] for d in derived), Decimal("0"))
        line_tax = sum((d[1] for d in derived), Decimal("0"))
        line_total = sum((d[2] for d in derived), Decimal("0"))

        for declared, computed, field, code in (
            (data.subtotal, line_subtotal, "subtotal", "LINE_TOTAL_MISMATCH"),
            (data.tax, line_tax, "tax", "TAX_MISMATCH"),
            (data.total, line_total, "total", "LINE_TOTAL_MISMATCH"),
        ):
            if declared != computed:
                issues.append(
                    {
                        "code": code,
                        "field": field,
                        "message": (
                            f"{field} is {declared}, but the line items "
                            f"sum to {computed}"
                        ),
                    }
                )

        return issues
