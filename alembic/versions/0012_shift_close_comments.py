"""comments for shortages in shift close reports"""
from alembic import op
import sqlalchemy as sa

revision = "0012_shift_close_comments"
down_revision = "0011_shift_close_reports"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("shift_close_reports", sa.Column("cash_comment", sa.Text(), nullable=True))
    op.add_column("shift_close_stock_items", sa.Column("comment", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("shift_close_stock_items", "comment")
    op.drop_column("shift_close_reports", "cash_comment")
