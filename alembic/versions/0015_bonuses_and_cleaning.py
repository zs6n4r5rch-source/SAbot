"""bonus rules, manual non-monetary review bonuses and cleaning performer"""
from alembic import op
import sqlalchemy as sa

revision = "0015_bonuses_and_cleaning"
down_revision = "0014_merge_shift_close_heads"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("shift_close_reports", sa.Column("cleaning_performed_by", sa.String(255), nullable=True))
    op.create_table(
        "non_monetary_bonuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bonus_type", sa.String(50), nullable=False, server_default="review"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_non_monetary_bonuses_employee_id", "non_monetary_bonuses", ["employee_id"])
    op.create_index("ix_non_monetary_bonuses_created_at", "non_monetary_bonuses", ["created_at"])

def downgrade():
    op.drop_index("ix_non_monetary_bonuses_created_at", table_name="non_monetary_bonuses")
    op.drop_index("ix_non_monetary_bonuses_employee_id", table_name="non_monetary_bonuses")
    op.drop_table("non_monetary_bonuses")
    op.drop_column("shift_close_reports", "cleaning_performed_by")
