from sqlalchemy.orm import Session

from app.models.import_job import ImportJob


class ImportJobRepository:
    """Persistence for import jobs, and nothing else.

    Only create() so far. get_by_id() has no caller until Phase 20 adds
    GET /imports/{import_id}, and Phase 8 established that a method with no
    caller is dead code nothing proves works.
    """

    def __init__(self, session: Session):
        self.session = session

    def create(self, job: ImportJob) -> ImportJob:
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job
