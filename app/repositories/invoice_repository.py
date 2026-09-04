from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.invoice import Invoice


class InvoiceRepository:
    """Persistence for invoices, and nothing else.

    This class knows how to store and retrieve invoices. It does not know
    whether an invoice is any good: not whether its totals add up, not whether
    its currency is supported, not whether it should have been accepted at all.
    Hand it a nonsense invoice and it will store the nonsense faithfully.

    That ignorance is the point. Deciding what may be stored belongs to the
    caller, which keeps this class usable by anything that needs to save an
    invoice -- an HTTP route today, the Excel importer in Phase 20, the
    document extractor in Phase 38 -- without each of them inheriting the
    others' idea of what is valid.
    """

    def __init__(self, session: Session):
        # The session is handed in rather than created here. A repository that
        # opened its own session could never share a transaction with anything
        # else, which is exactly what Phase 22 will need.
        self.session = session

    def create(self, invoice: Invoice) -> Invoice:
        self.session.add(invoice)
        self.session.commit()
        # The database assigned the id; refresh re-reads the row so the caller
        # can see it.
        self.session.refresh(invoice)
        return invoice

    def get_by_id(self, invoice_id: int) -> Invoice | None:
        return self.session.get(Invoice, invoice_id)

    def find_by_vendor_and_invoice_number(
        self, vendor: str, invoice_number: str
    ) -> Invoice | None:
        # Answers "does this row exist", not "is this allowed". The caller
        # decides what an existing row means.
        return self.session.scalars(
            select(Invoice).where(
                Invoice.vendor == vendor,
                Invoice.invoice_number == invoice_number,
            )
        ).first()

    def list_all(self) -> list[Invoice]:
        # Named list_all rather than list: a method called `list` shadows the
        # builtin for every later annotation in this class body, so a
        # subsequent `-> list[Invoice]` would raise TypeError.
        #
        # A table has no inherent row order, so the ordering is explicit.
        return list(self.session.scalars(select(Invoice).order_by(Invoice.id)).all())
