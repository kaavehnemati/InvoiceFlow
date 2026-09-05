from sqlalchemy.orm import Session

from app.models.import_job import ImportError, ImportJob


class ImportJobRepository:
    """Persistence for import jobs, and nothing else.

    get_by_id() gained its caller in Phase 20, which is when Phase 8's rule
    said to write it: a method with no caller is dead code nothing proves
    works.
    """

    def __init__(self, session: Session):
        self.session = session

    def create(self, job: ImportJob) -> ImportJob:
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def get_by_id(self, import_id: str) -> ImportJob | None:
        return self.session.get(ImportJob, import_id)

    def save_with_errors(self, job: ImportJob, errors: list[ImportError]) -> ImportJob:
        """Persist the job's counts and everything that went wrong, together."""
        self.session.add(job)
        for error in errors:
            self.session.add(error)
        self.session.commit()
        self.session.refresh(job)
        return job
