"""unique index on binder_placement cell

Guards the invariant docs/02-data-model.md calls a cheap backstop: two placements can never
claim the same top-left pocket of the same page. Overlap between differently-anchored spans is
still the service layer's job -- this only catches exact-cell collisions, which are the ones a
buggy client is most likely to produce.

Revision ID: a1f4c9d7e2b3
Revises: c8364ca2a717
Create Date: 2026-08-27 00:00:00.000000
"""
from alembic import op

revision = 'a1f4c9d7e2b3'
down_revision = 'c8364ca2a717'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'uq_binder_placement_cell',
        'binder_placement',
        ['binder_id', 'page_index', 'row', 'col'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_binder_placement_cell', table_name='binder_placement')
