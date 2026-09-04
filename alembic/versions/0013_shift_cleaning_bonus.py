"""night shift cleaning confirmation and bonus"""
from alembic import op
import sqlalchemy as sa

revision = "0013_shift_cleaning_bonus"
down_revision = "0012_shift_close_comments"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("shift_close_reports", sa.Column("cleaning_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("shift_close_reports", sa.Column("cleaning_bonus_amount", sa.Numeric(14, 2), nullable=True))

def downgrade():
    op.drop_column("shift_close_reports", "cleaning_bonus_amount")
    op.drop_column("shift_close_reports", "cleaning_confirmed_at")
