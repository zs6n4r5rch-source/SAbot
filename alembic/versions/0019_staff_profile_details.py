"""add local staff profile details for real staff seed"""
from alembic import op
import sqlalchemy as sa

revision = "0019_staff_profile_details"
down_revision = "0018_real_staff_profiles"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("access_profiles", sa.Column("salary_per_shift", sa.Numeric(14, 2), nullable=True))
    op.add_column("access_profiles", sa.Column("cleaning_bonus_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("access_profiles", sa.Column("ideal_close_bonus_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("access_profiles", sa.Column("cash_discipline_bonus_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("access_profiles", sa.Column("bar_bonus_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("access_profiles", sa.Column("employment_start_date", sa.Date(), nullable=True))
    op.add_column("access_profiles", sa.Column("notes", sa.Text(), nullable=True))

    op.execute("UPDATE access_profiles SET salary_per_shift = 2000.00 WHERE role = 'admin'")
    op.execute("UPDATE access_profiles SET cleaning_bonus_enabled = true, ideal_close_bonus_enabled = true, cash_discipline_bonus_enabled = true, bar_bonus_enabled = true WHERE role = 'admin'")
    op.execute("UPDATE access_profiles SET cleaning_bonus_enabled = false, ideal_close_bonus_enabled = false, cash_discipline_bonus_enabled = false, bar_bonus_enabled = false WHERE role = 'owner'")

def downgrade():
    op.drop_column("access_profiles", "notes")
    op.drop_column("access_profiles", "employment_start_date")
    op.drop_column("access_profiles", "bar_bonus_enabled")
    op.drop_column("access_profiles", "cash_discipline_bonus_enabled")
    op.drop_column("access_profiles", "ideal_close_bonus_enabled")
    op.drop_column("access_profiles", "cleaning_bonus_enabled")
    op.drop_column("access_profiles", "salary_per_shift")
