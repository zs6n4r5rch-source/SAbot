"""historical duplicate: dismissal_required is introduced by 0017"""

revision = "0023_salary_violation_dismissal"
down_revision = "0022_salary_and_shift_close"
branch_labels = None
depends_on = None


def upgrade():
    # 0017_dismissal_required already creates the column and its index.
    # Keep this historical revision as a no-op so fresh installs converge.
    pass


def downgrade():
    pass
