"""historical duplicate: salary and shift-close fields are already represented by earlier revisions"""

revision = "0022_salary_and_shift_close"
down_revision = "0021_inventory_min_stock_five"
branch_labels = None
depends_on = None


def upgrade():
    # Salary tables are part of the 0001 core snapshot; shift-close fields are
    # introduced by 0011-0015. This revision was a later duplicate consolidation
    # and must not recreate those objects on a fresh database.
    pass


def downgrade():
    pass
