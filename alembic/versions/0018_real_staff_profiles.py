"""add real staff access profiles and Telegram binding requests"""
from alembic import op
import sqlalchemy as sa

revision = "0018_real_staff_profiles"
down_revision = "0017_dismissal_required"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "access_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('admin','owner')", name="ck_access_profiles_role"),
    )
    op.create_index("ix_access_profiles_username", "access_profiles", ["username"], unique=True)
    op.create_index("ix_access_profiles_employee_id", "access_profiles", ["employee_id"], unique=False)
    op.create_table(
        "telegram_binding_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("access_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','approved','rejected')", name="ck_binding_requests_status"),
    )
    op.create_index("ix_telegram_binding_requests_profile_id", "telegram_binding_requests", ["profile_id"])
    op.create_index("ix_telegram_binding_requests_telegram_id", "telegram_binding_requests", ["telegram_id"])
    op.create_index("ix_telegram_binding_requests_status", "telegram_binding_requests", ["status"])
    op.create_index("ix_binding_requests_pending_profile", "telegram_binding_requests", ["profile_id", "status"])


def downgrade():
    op.drop_index("ix_binding_requests_pending_profile", table_name="telegram_binding_requests")
    op.drop_index("ix_telegram_binding_requests_status", table_name="telegram_binding_requests")
    op.drop_index("ix_telegram_binding_requests_telegram_id", table_name="telegram_binding_requests")
    op.drop_index("ix_telegram_binding_requests_profile_id", table_name="telegram_binding_requests")
    op.drop_table("telegram_binding_requests")
    op.drop_index("ix_access_profiles_employee_id", table_name="access_profiles")
    op.drop_index("ix_access_profiles_username", table_name="access_profiles")
    op.drop_table("access_profiles")
