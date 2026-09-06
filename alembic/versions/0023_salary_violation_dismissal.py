"""add dismissal flag to salary violations"""
from alembic import op
import sqlalchemy as sa

revision = "0023_salary_violation_dismissal"
down_revision = "0022_salary_and_shift_close"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "salary_violations",
        sa.Column("dismissal_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("salary_violations", "dismissal_required")
