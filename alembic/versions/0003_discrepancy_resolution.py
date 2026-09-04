"""add discrepancy resolution audit fields"""
from alembic import op
import sqlalchemy as sa

revision = "0003_discrepancy_resolution"
down_revision = "0002_clients_loyalty_mailing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("discrepancies", sa.Column("resolved_by", sa.BigInteger(), nullable=True))
    op.add_column("discrepancies", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("discrepancies", sa.Column("resolution_comment", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("discrepancies", "resolution_comment")
    op.drop_column("discrepancies", "resolved_at")
    op.drop_column("discrepancies", "resolved_by")
