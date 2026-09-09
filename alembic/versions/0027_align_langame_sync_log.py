"""align LANGAME sync audit log schema with the ORM model."""
from alembic import op
import sqlalchemy as sa

revision = "0027_align_langame_sync_log"
down_revision = "0026_enforce_inventory_min_stock_default"
branch_labels = None
depends_on = None


def upgrade():
    # Production databases created by the earlier migration use `resource`,
    # while the current ORM/scheduler contract uses `sync_type`.
    op.alter_column("langame_sync_log", "resource", new_column_name="sync_type")
    op.add_column(
        "langame_sync_log",
        sa.Column("records_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("langame_sync_log", "records_count")
    op.alter_column("langame_sync_log", "sync_type", new_column_name="resource")
