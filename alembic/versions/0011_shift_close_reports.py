"""shift close cash and stock reports"""
from alembic import op
import sqlalchemy as sa

revision = "0011_shift_close_reports"
down_revision = "0010_shift_financial_channels"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shift_close_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("cash_expected", sa.Numeric(14,2), nullable=True),
        sa.Column("cash_actual", sa.Numeric(14,2), nullable=True),
        sa.Column("cash_difference", sa.Numeric(14,2), nullable=True),
        sa.Column("stock_items_count", sa.Integer(), nullable=True),
        sa.Column("stock_discrepancies_count", sa.Integer(), nullable=True),
        sa.Column("first_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "shift_close_stock_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("shift_close_reports.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False, index=True),
        sa.Column("langame_quantity", sa.Numeric(14,3), nullable=False),
        sa.Column("actual_quantity", sa.Numeric(14,3), nullable=True),
        sa.Column("difference", sa.Numeric(14,3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("shift_close_stock_items")
    op.drop_table("shift_close_reports")
