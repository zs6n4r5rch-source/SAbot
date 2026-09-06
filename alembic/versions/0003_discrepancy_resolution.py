"""historical duplicate: discrepancy resolution fields are in the initial core schema"""

revision = "0003_discrepancy_resolution"
down_revision = "0002_clients_loyalty_mailing"
branch_labels = None
depends_on = None


def upgrade():
    # 0001_initial creates the current core-model snapshot, including these fields.
    # Keep this revision as a no-op so fresh installs and upgraded installs converge.
    pass


def downgrade():
    pass
