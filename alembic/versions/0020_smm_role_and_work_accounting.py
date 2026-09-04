"""add dedicated SMM access and work accounting"""
from alembic import op
import sqlalchemy as sa

revision = "0020_smm_role_and_work_accounting"
down_revision = "0019_staff_profile_details"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "smm_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("analytics_access", sa.String(length=1000), nullable=False, server_default="social,guests,marketing,advertising"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "smm_task_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_type", sa.String(length=50), nullable=False, unique=True, index=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False, server_default="шт"),
        sa.Column("rate", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "smm_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("task_type", sa.String(length=50), nullable=False, index=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("unit", sa.String(length=50), nullable=False, server_default="шт"),
        sa.Column("unit_rate", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="submitted", index=True),
        sa.Column("proof", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('submitted','approved','rejected')", name="ck_smm_tasks_status"),
    )
    op.execute("INSERT INTO smm_task_rates (task_type,title,unit,rate,active) VALUES ('post','Публикация','шт',0,true),('story','Stories','шт',0,true),('reel','Короткое видео','шт',0,true),('campaign','Рекламная кампания','кампания',0,true),('report','Отчёт/аналитика','отчёт',0,true)")


def downgrade():
    op.drop_table("smm_tasks")
    op.drop_table("smm_task_rates")
    op.drop_table("smm_access")
