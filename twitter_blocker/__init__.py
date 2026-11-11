"""Bulk blocker for Twitter/X accounts.

Public classes: BulkBlockManager (orchestration), TwitterAPI (API access),
DatabaseManager (SQLite block history).
"""

from .api import TwitterAPI
from .database import DatabaseManager
from .manager import BulkBlockManager
from .version import __version__

__all__ = ["BulkBlockManager", "TwitterAPI", "DatabaseManager", "__version__"]
