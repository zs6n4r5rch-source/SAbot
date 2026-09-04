"""add guests, loyalty groups and marketing tables"""
from alembic import op
import sqlalchemy as sa

revision = "0002_clients_loyalty_mailing"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("guests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("langame_guest_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("fio", sa.String(255)), sa.Column("phone", sa.String(64)),
        sa.Column("is_temp", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_virtual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_guests_langame_guest_id", "guests", ["langame_guest_id"])
    op.create_index("ix_guests_phone", "guests", ["phone"])
    op.create_table("guest_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("langame_group_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("percent", sa.Integer()), sa.Column("bonus_birthday", sa.Boolean()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_guest_groups_langame_group_id", "guest_groups", ["langame_group_id"])
    op.create_table("guest_group_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guest_id", sa.Integer(), sa.ForeignKey("guests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guest_group_id", sa.Integer(), sa.ForeignKey("guest_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("guest_id", "guest_group_id"),
    )
    op.create_index("ix_guest_group_members_guest_id", "guest_group_members", ["guest_id"])
    op.create_index("ix_guest_group_members_guest_group_id", "guest_group_members", ["guest_group_id"])
    op.create_table("guest_telegram",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guest_id", sa.Integer(), sa.ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("marketing_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("marketing_consent_at", sa.DateTime(timezone=True)),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_guest_telegram_guest_id", "guest_telegram", ["guest_id"])
    op.create_index("ix_guest_telegram_telegram_user_id", "guest_telegram", ["telegram_user_id"])
    op.create_table("marketing_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.BigInteger(), nullable=False), sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_marketing_campaigns_status", "marketing_campaigns", ["status"])
    op.create_table("marketing_campaign_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guest_group_id", sa.Integer(), sa.ForeignKey("guest_groups.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("campaign_id", "guest_group_id"),
    )
    op.create_index("ix_marketing_campaign_groups_campaign_id", "marketing_campaign_groups", ["campaign_id"])
    op.create_index("ix_marketing_campaign_groups_guest_group_id", "marketing_campaign_groups", ["guest_group_id"])
    op.create_table("marketing_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guest_id", sa.Integer(), sa.ForeignKey("guests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True)), sa.Column("error", sa.Text()),
        sa.UniqueConstraint("campaign_id", "guest_id"),
    )
    op.create_index("ix_marketing_recipients_campaign_id", "marketing_recipients", ["campaign_id"])
    op.create_index("ix_marketing_recipients_guest_id", "marketing_recipients", ["guest_id"])
    op.create_index("ix_marketing_recipients_status", "marketing_recipients", ["status"])


def downgrade():
    op.drop_table("marketing_recipients")
    op.drop_table("marketing_campaign_groups")
    op.drop_table("marketing_campaigns")
    op.drop_table("guest_telegram")
    op.drop_table("guest_group_members")
    op.drop_table("guest_groups")
    op.drop_table("guests")
