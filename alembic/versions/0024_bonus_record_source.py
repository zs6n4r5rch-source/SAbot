"""add source key to bonus records for idempotent imports"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0024_bonus_record_source"
down_revision = "0023_salary_violation_dismissal"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    if "bonus_records" not in tables:
        op.create_table(
            "bonus_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "employee_id",
                sa.Integer(),
                sa.ForeignKey("employees.id"),
                nullable=False,
            ),
            sa.Column(
                "shift_id",
                sa.Integer(),
                sa.ForeignKey("shifts.id"),
                nullable=True,
            ),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=True),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_bonus_records_employee_id",
            "bonus_records",
            ["employee_id"],
        )
        op.create_index(
            "ix_bonus_records_shift_id",
            "bonus_records",
            ["shift_id"],
        )
        op.create_index(
            "ix_bonus_records_created_at",
            "bonus_records",
            ["created_at"],
        )
    else:
        columns = {column["name"] for column in inspector.get_columns("bonus_records")}
        if "source" not in columns:
            op.add_column(
                "bonus_records",
                sa.Column("source", sa.String(length=64), nullable=True),
            )
        if "source_id" not in columns:
            op.add_column(
                "bonus_records",
                sa.Column("source_id", sa.String(length=128), nullable=True),
            )

    indexes = {index["name"] for index in inspect(bind).get_indexes("bonus_records")}
    if "ix_bonus_records_source" not in indexes:
        op.create_index(
            "ix_bonus_records_source",
            "bonus_records",
            ["source", "source_id"],
            unique=True,
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "bonus_records" not in inspector.get_table_names():
        return

    indexes = {index["name"] for index in inspector.get_indexes("bonus_records")}
    if "ix_bonus_records_source" in indexes:
        op.drop_index("ix_bonus_records_source", table_name="bonus_records")

    columns = {column["name"] for column in inspector.get_columns("bonus_records")}
    if "source_id" in columns:
        op.drop_column("bonus_records", "source_id")
    if "source" in columns:
        op.drop_column("bonus_records", "source")
