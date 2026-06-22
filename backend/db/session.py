"""
backend/db/session.py
Database connection configuration and session makers (connecting to PostgreSQL/Neon).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)
