"""Binder layouts. Placements are rectangles on a pocket grid; see docs/05-binder-spec.md."""
from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import PlacementKind


class Binder(Base, TimestampMixin):
    __tablename__ = "binder"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    rows: Mapped[int] = mapped_column(default=3)
    cols: Mapped[int] = mapped_column(default=3)
    pages: Mapped[int] = mapped_column(default=20)
    # Gutter-spanning inserts require side-loading pages -- enforced in the service layer.
    is_side_loading: Mapped[bool] = mapped_column(Boolean, default=True)
    gutter_mm: Mapped[int] = mapped_column(default=6)
    notes: Mapped[str | None] = mapped_column(String(1024))


class InsertAsset(Base, TimestampMixin):
    __tablename__ = "insert_asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    image_path: Mapped[str] = mapped_column(String(512))
    width_pockets: Mapped[int] = mapped_column(default=1)
    height_pockets: Mapped[int] = mapped_column(default=1)
    dpi: Mapped[int | None]
    source_note: Mapped[str | None] = mapped_column(String(512))


class BinderPlacement(Base, TimestampMixin):
    __tablename__ = "binder_placement"
    # A cheap backstop for the real guard in services/binder.py: two placements can never claim
    # the same top-left pocket. Overlap between differently-anchored spans still needs the
    # service-layer interval check -- this index only catches exact-cell collisions.
    __table_args__ = (
        Index(
            "uq_binder_placement_cell",
            "binder_id",
            "page_index",
            "row",
            "col",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    binder_id: Mapped[int] = mapped_column(ForeignKey("binder.id", ondelete="CASCADE"))
    page_index: Mapped[int]
    row: Mapped[int]
    col: Mapped[int]
    row_span: Mapped[int] = mapped_column(default=1)
    col_span: Mapped[int] = mapped_column(default=1)
    kind: Mapped[PlacementKind] = mapped_column(String(8))
    card_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_variant.id", ondelete="SET NULL")
    )
    insert_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("insert_asset.id", ondelete="SET NULL")
    )
    spans_gutter: Mapped[bool] = mapped_column(Boolean, default=False)
    z_order: Mapped[int] = mapped_column(default=0)
