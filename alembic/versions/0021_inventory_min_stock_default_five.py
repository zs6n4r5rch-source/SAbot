"""set critical inventory stock threshold to five units"""
from alembic import op
import sqlalchemy as sa

revision = "0021_inventory_min_stock_default_five"
down_revision = "0020_smm_role_and_work_accounting"
branch_labels = None
depends_on = None


def upgrade():
    # Apply the new critical threshold to every existing product balance.
    op.execute("UPDATE inventory_balances SET min_stock = 5")
    # Keep future balances consistent even when the application omits min_stock.
    op.alter_column(
        "inventory_balances",
        "min_stock",
        existing_type=sa.Numeric(14, 3),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        server_default=sa.text("5"),
    )


def downgrade():
    op.alter_column(
        "inventory_balances",
        "min_stock",
        existing_type=sa.Numeric(14, 3),
        existing_nullable=False,
        existing_server_default=sa.text("5"),
        server_default=sa.text("0"),
    )
