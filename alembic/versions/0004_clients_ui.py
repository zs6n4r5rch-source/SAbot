"""client management UI cache indexes"""
from alembic import op
import sqlalchemy as sa

revision = "0004_clients_ui"
down_revision = "0003_discrepancy_resolution"
branch_labels = None
depends_on = None

def upgrade():
    op.create_index("ix_guest_group_members_guest_group_guest", "guest_group_members", ["guest_group_id", "guest_id"])

def downgrade():
    op.drop_index("ix_guest_group_members_guest_group_guest", table_name="guest_group_members")
