import pytest
from app.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db() -> Session:
    """In-memory SQLite session with all tables created via create_all.

    create_all (not Alembic) is fine here -- tests are the documented exception in
    docs/02-data-model.md ("do not use create_all outside tests").
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
