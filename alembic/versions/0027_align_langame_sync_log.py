"""align LANGAME sync audit log schema with the ORM model."""
from alembic import op
import sqlalchemy as sa

revision = "0027_align_langame_sync_log"
down_revision = "0026_enforce_inventory_min_stock_default"
branch_labels = None
depends_on = None


def _columns():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {c["name"] for c in inspector.get_columns("langame_sync_log")}


def upgrade():
    # Some historical databases used `resource`, while fresh databases created
    # from the current ORM already have `sync_type`. Make the migration valid
    # for both schemas and keep it idempotent with respect to those columns.
    columns = _columns()
    if "resource" in columns and "sync_type" not in columns:
        op.alter_column("langame_sync_log", "resource", new_column_name="sync_type")
    if "records_count" not in columns:
        op.add_column(
            "langame_sync_log",
            sa.Column("records_count", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade():
    columns = _columns()
    if "records_count" in columns:
        op.drop_column("langame_sync_log", "records_count")
    columns = _columns()
    if "sync_type" in columns and "resource" not in columns:
        op.alter_column("langame_sync_log", "sync_type", new_column_name="resource")
