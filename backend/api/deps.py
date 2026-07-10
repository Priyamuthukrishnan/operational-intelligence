"""
api/deps.py
Dependency injection providers (such as DB session generators and external client helpers).
"""

from collections.abc import Generator

from sqlalchemy.orm import Session

from db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and ensure it is closed after the request.

    Usage in FastAPI endpoints::

        @router.post("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
