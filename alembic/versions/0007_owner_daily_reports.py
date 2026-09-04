"""owner daily report delivery log"""
from alembic import op
import sqlalchemy as sa

revision = "0007_owner_daily_reports"
down_revision = "0006_guest_telegram_consent"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "owner_daily_report_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("owner_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="sending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint("report_date", "owner_telegram_id"),
    )
    op.create_index("ix_owner_daily_report_deliveries_report_date", "owner_daily_report_deliveries", ["report_date"])
    op.create_index("ix_owner_daily_report_deliveries_owner_telegram_id", "owner_daily_report_deliveries", ["owner_telegram_id"])


def downgrade():
    op.drop_index("ix_owner_daily_report_deliveries_owner_telegram_id", table_name="owner_daily_report_deliveries")
    op.drop_index("ix_owner_daily_report_deliveries_report_date", table_name="owner_daily_report_deliveries")
    op.drop_table("owner_daily_report_deliveries")
