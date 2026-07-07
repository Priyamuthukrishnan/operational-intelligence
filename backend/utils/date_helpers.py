"""
backend/utils/date_helpers.py
Utility helper functions for timezone formatting, range configurations, and dashboard rolling window durations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def get_daily_key(dt: Optional[datetime]) -> str:
    """Format a datetime as daily key: YYYY-MM-DD."""
    if dt is None:
        return "unknown"
    return dt.date().isoformat()


def get_weekly_key(dt: Optional[datetime]) -> str:
    """Format a datetime as weekly ISO 8601 key: YYYY-Www."""
    if dt is None:
        return "unknown"
    return dt.strftime("%G-W%V")


def get_monthly_key(dt: Optional[datetime]) -> str:
    """Format a datetime as monthly key: YYYY-MM."""
    if dt is None:
        return "unknown"
    return dt.strftime("%Y-%m")


def get_date_range_window(days: int) -> tuple[datetime, datetime]:
    """Get UTC start and end timestamps representing a rolling window of N days.

    Args:
        days: Duration in days.

    Returns:
        A tuple of (start_datetime, end_datetime) in UTC timezone.
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    return start, now
