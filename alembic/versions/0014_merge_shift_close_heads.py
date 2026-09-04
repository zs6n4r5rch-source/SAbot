"""merge the shortage-reasons and cleaning-bonus migration heads"""

revision = "0014_merge_shift_close_heads"
down_revision = ("0013_shift_shortage_reasons", "0013_shift_cleaning_bonus")
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
