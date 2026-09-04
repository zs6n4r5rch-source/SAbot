"""salary violations and automatic/manual penalties"""
from alembic import op
import sqlalchemy as sa

revision = "0016_salary_violations"
down_revision = "0015_bonuses_and_cleaning"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "salary_violations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_code", sa.String(80), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(14,2), nullable=False, server_default="0"),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("source_key", sa.String(255), nullable=True),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("premium_reduction_percent", sa.Numeric(5,2), nullable=False, server_default="0"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_salary_violations_employee_id", "salary_violations", ["employee_id"])
    op.create_index("ix_salary_violations_rule_code", "salary_violations", ["rule_code"])
    op.create_index("ix_salary_violations_source", "salary_violations", ["source"])
    op.create_index("ix_salary_violations_shift_id", "salary_violations", ["shift_id"])
    op.create_index("ix_salary_violations_created_at", "salary_violations", ["created_at"])
    op.create_unique_constraint("uq_salary_violations_source_key", "salary_violations", ["source_key"])

def downgrade():
    op.drop_constraint("uq_salary_violations_source_key", "salary_violations", type_="unique")
    for name in ["ix_salary_violations_created_at","ix_salary_violations_shift_id","ix_salary_violations_source","ix_salary_violations_rule_code","ix_salary_violations_employee_id"]:
        op.drop_index(name, table_name="salary_violations")
    op.drop_table("salary_violations")
