"""add salary tables and extended shift close fields"""
from alembic import op
import sqlalchemy as sa

revision = "0022_salary_and_shift_close"
down_revision = "0021_inventory_min_stock_five"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "salary_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("rule_type", sa.String(50), nullable=False),
        sa.Column("value", sa.Numeric(14, 4), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "salary_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("base_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("bonus_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
        sa.Column("confirmed_by", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("employee_id", "date_from", "date_to"),
    )
    op.create_table(
        "salary_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("salary_period_id", sa.Integer(), sa.ForeignKey("salary_periods.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "salary_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("salary_period_id", sa.Integer(), sa.ForeignKey("salary_periods.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_by", sa.BigInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_table(
        "non_monetary_bonuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("bonus_type", sa.String(50), nullable=False, server_default="review"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )

    op.add_column("shift_close_reports", sa.Column("cash_shortage_reason", sa.String(100), nullable=True))
    op.add_column("shift_close_reports", sa.Column("cash_comment", sa.Text(), nullable=True))
    op.add_column("shift_close_reports", sa.Column("cleaning_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("shift_close_reports", sa.Column("cleaning_performed_by", sa.String(255), nullable=True))
    op.add_column("shift_close_reports", sa.Column("cleaning_bonus_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("shift_close_stock_items", sa.Column("shortage_reason", sa.String(100), nullable=True))
    op.add_column("shift_close_stock_items", sa.Column("comment", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("shift_close_stock_items", "comment")
    op.drop_column("shift_close_stock_items", "shortage_reason")
    op.drop_column("shift_close_reports", "cleaning_bonus_amount")
    op.drop_column("shift_close_reports", "cleaning_performed_by")
    op.drop_column("shift_close_reports", "cleaning_confirmed_at")
    op.drop_column("shift_close_reports", "cash_comment")
    op.drop_column("shift_close_reports", "cash_shortage_reason")
    op.drop_table("non_monetary_bonuses")
    op.drop_table("salary_payments")
    op.drop_table("salary_adjustments")
    op.drop_table("salary_periods")
    op.drop_table("salary_rules")
