"""historical duplicate: shift financial channels are in the initial core schema"""

revision = "0010_shift_financial_channels"
down_revision = "0009_cleanup_owner_report_index"
branch_labels = None
depends_on = None


def upgrade():
    # 0001_initial creates the current core-model snapshot, including these fields.
    # Keep this revision as a no-op so fresh installs and upgraded installs converge.
    pass


def downgrade():
    pass
