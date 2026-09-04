"""owner report settings"""
from alembic import op
import sqlalchemy as sa
revision = "0008_owner_report_settings"
down_revision = "0007_owner_daily_reports"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("owner_report_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("report_timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("report_hour", sa.Integer(), nullable=False, server_default="9"),
        sa.Column("report_minute", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("include_sales", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("include_shifts", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("include_inventory", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("include_discrepancies", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("include_salary", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("include_clients", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("send_excel", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_owner_report_settings_owner_telegram_id", "owner_report_settings", ["owner_telegram_id"], unique=True)
def downgrade():
    op.drop_index("ix_owner_report_settings_owner_telegram_id", table_name="owner_report_settings")
    op.drop_table("owner_report_settings")
