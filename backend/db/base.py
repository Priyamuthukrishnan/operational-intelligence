"""
db/base.py
Imports SQLAlchemy Base and all database models in a single location for migration tools (like Alembic).
"""

# Re-export the declarative base so Alembic's env.py can do:
#   from db.base import Base
from db.base_class import Base  # noqa: F401

# Import every model so that Base.metadata contains all tables.
from models.operational_analysis import OperationalAnalysis  # noqa: F401
from models.issue_cluster import IssueCluster  # noqa: F401
from models.customer_health import CustomerHealth  # noqa: F401
from models.ticket_rollup import TicketRollup  # noqa: F401
