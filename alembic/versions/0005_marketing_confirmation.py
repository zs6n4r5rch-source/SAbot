"""add owner confirmation metadata to marketing campaigns"""
from alembic import op
import sqlalchemy as sa

revision = "0005_marketing_confirmation"
down_revision = "0004_clients_ui"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("marketing_campaigns", sa.Column("confirmed_by", sa.BigInteger(), nullable=True))
    op.add_column("marketing_campaigns", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("marketing_campaigns", "confirmed_at")
    op.drop_column("marketing_campaigns", "confirmed_by")
