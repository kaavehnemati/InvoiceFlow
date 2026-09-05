from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# The engine owns the connection pool. One per process; it does not connect
# until something actually runs a statement.
#
# str() because PostgresDsn is a parsed URL object, not a string. It round-trips
# unchanged, so SQLAlchemy receives exactly what was configured.
engine = create_engine(str(settings.database_url))

# A factory, not a session. Call SessionLocal() to start a new unit of work.
SessionLocal = sessionmaker(bind=engine, autoflush=False)
