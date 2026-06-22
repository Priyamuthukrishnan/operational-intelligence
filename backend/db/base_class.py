"""
backend/db/base_class.py
Declarative Base for SQLAlchemy ORM models. Provides dynamic name configuration.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Application-wide declarative base.

    All ORM models inherit from this class so that Alembic and session
    machinery share a single metadata registry.
    """

    pass
