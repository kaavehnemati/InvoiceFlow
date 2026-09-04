from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared base for every ORM model.

    Each subclass registers its table on ``Base.metadata``, which is how
    ``create_all()`` knows what to build. This lives apart from session.py so a
    model can import Base without dragging in the engine and a live database
    connection along with it.
    """
