"""Shared FastAPI dependencies. Re-exports app.db.get_db under the conventional api.deps path."""
from app.db import get_db

__all__ = ["get_db"]
