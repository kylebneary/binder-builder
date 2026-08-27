"""Database engine and session management."""
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

_is_sqlite = _settings.database_url.startswith("sqlite")


def enable_sqlite_foreign_keys(engine_: Engine) -> None:
    """Turn on SQLite's foreign-key enforcement for every connection this engine opens.

    SQLite ships with `PRAGMA foreign_keys` OFF and applies it per connection, so without this
    the fifteen `ondelete="CASCADE"` clauses in app/models are silently inert: deleting a binder
    leaves its `binder_placement` rows behind pointing at nothing, and the same goes for goals,
    sets and pull-rate profiles. Postgres enforces them, so skipping this would also mean the two
    supported engines behave differently -- which the Postgres-compatibility rule in CLAUDE.md
    exists to prevent. Attached per engine rather than globally so a caller building its own
    engine (the test fixtures) opts in explicitly.
    """

    @event.listens_for(engine_, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


engine = create_engine(
    _settings.database_url,
    echo=False,
    # SQLite needs this for FastAPI's threadpool; harmless to guard on the scheme.
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

if _is_sqlite:
    enable_sqlite_foreign_keys(engine)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
