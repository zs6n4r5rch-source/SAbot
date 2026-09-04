"""add guest Telegram invite tokens for self-linking and consent"""
from alembic import op
import sqlalchemy as sa

revision = "0006_guest_telegram_consent"
down_revision = "0005_marketing_confirmation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "guest_link_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("guest_id", sa.Integer(), sa.ForeignKey("guests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_guest_link_tokens_token", "guest_link_tokens", ["token"], unique=True)
    op.create_index("ix_guest_link_tokens_guest_id", "guest_link_tokens", ["guest_id"])
    op.create_index("ix_guest_link_tokens_expires_at", "guest_link_tokens", ["expires_at"])


def downgrade():
    op.drop_index("ix_guest_link_tokens_expires_at", table_name="guest_link_tokens")
    op.drop_index("ix_guest_link_tokens_guest_id", table_name="guest_link_tokens")
    op.drop_index("ix_guest_link_tokens_token", table_name="guest_link_tokens")
    op.drop_table("guest_link_tokens")
