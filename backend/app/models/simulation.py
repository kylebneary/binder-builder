"""Persisted simulation runs. Every result is reproducible from these fields."""
from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SimulationRun(Base, TimestampMixin):
    __tablename__ = "simulation_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goal.id", ondelete="CASCADE"))
    params_json: Mapped[dict] = mapped_column(JSON)
    strategy_json: Mapped[dict] = mapped_column(JSON)
    n_trials: Mapped[int]
    seed: Mapped[int]
    # The price date the run used. Displayed with every result so a changed answer can be
    # attributed to moved prices rather than a changed model.
    price_date: Mapped[str] = mapped_column(String(16))
    profile_version: Mapped[str | None] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(16), default="0.1.0")
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    results_json: Mapped[dict] = mapped_column(JSON)
