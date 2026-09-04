"""structured shortage reasons for shift close reports"""
from alembic import op
import sqlalchemy as sa

revision = "0013_shift_shortage_reasons"
down_revision = "0012_shift_close_comments"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("shift_close_reports", sa.Column("cash_shortage_reason", sa.String(100), nullable=True))
    op.add_column("shift_close_stock_items", sa.Column("shortage_reason", sa.String(100), nullable=True))

def downgrade():
    op.drop_column("shift_close_stock_items", "shortage_reason")
    op.drop_column("shift_close_reports", "cash_shortage_reason")
