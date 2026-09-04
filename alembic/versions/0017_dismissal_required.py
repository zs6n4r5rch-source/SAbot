"""mark repeat insult-SA violations as requiring owner dismissal decision"""
from alembic import op
import sqlalchemy as sa

revision = "0017_dismissal_required"
down_revision = "0016_salary_violations"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("salary_violations", sa.Column("dismissal_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_salary_violations_dismissal_required", "salary_violations", ["dismissal_required"])

def downgrade():
    op.drop_index("ix_salary_violations_dismissal_required", table_name="salary_violations")
    op.drop_column("salary_violations", "dismissal_required")
