"""add source key to bonus records for idempotent imports"""
from alembic import op
import sqlalchemy as sa

revision = "0024_bonus_record_source"
down_revision = "0023_salary_violation_dismissal"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bonus_records",
        sa.Column("source", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "bonus_records",
        sa.Column("source_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_bonus_records_source",
        "bonus_records",
        ["source", "source_id"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_bonus_records_source", table_name="bonus_records")
    op.drop_column("bonus_records", "source_id")
    op.drop_column("bonus_records", "source")
