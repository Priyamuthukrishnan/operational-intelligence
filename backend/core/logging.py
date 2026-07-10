"""
core/logging.py
Structured logging initializations and standard output logging formatter helpers.
"""

import logging
import sys
from typing import Optional


def setup_logger(
    name: str,
    level: int = logging.INFO,
    fmt: Optional[str] = None,
) -> logging.Logger:
    """Create and return a structured logger with consistent formatting.

    Args:
        name: Logger namespace (typically ``__name__``).
        level: Minimum severity level.
        fmt: Optional custom format string.

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        # Avoid duplicate handlers on repeated calls.
        return logger

    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt
        or "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
