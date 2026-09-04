"""store LANGAME shift financial channels for read-only analytics"""
from alembic import op
import sqlalchemy as sa

revision = "0010_shift_financial_channels"
down_revision = "0009_cleanup_owner_report_index"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("shifts", sa.Column("cash_sales", sa.Numeric(14, 2), server_default="0", nullable=True))
    op.add_column("shifts", sa.Column("card_sales", sa.Numeric(14, 2), server_default="0", nullable=True))
    op.add_column("shifts", sa.Column("mobile_sales", sa.Numeric(14, 2), server_default="0", nullable=True))
    op.add_column("shifts", sa.Column("refunds_cash", sa.Numeric(14, 2), server_default="0", nullable=True))
    op.add_column("shifts", sa.Column("refunds_card", sa.Numeric(14, 2), server_default="0", nullable=True))
    op.add_column("shifts", sa.Column("collection", sa.Numeric(14, 2), server_default="0", nullable=True))


def downgrade():
    for name in ("collection", "refunds_card", "refunds_cash", "mobile_sales", "card_sales", "cash_sales"):
        op.drop_column("shifts", name)
