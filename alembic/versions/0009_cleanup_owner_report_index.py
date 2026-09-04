"""remove redundant unique index on owner report settings"""
from alembic import op

revision = "0009_cleanup_owner_report_index"
down_revision = "0008_owner_report_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_owner_report_settings_owner_telegram_id", table_name="owner_report_settings")


def downgrade():
    op.create_index(
        "ix_owner_report_settings_owner_telegram_id",
        "owner_report_settings",
        ["owner_telegram_id"],
        unique=True,
    )
