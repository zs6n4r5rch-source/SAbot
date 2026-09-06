"""reconcile inventory minimum stock threshold to five.

This is a data reconciliation, not a historical recreation of 0021.

Production was stamped at a later Alembic revision while the data change from
0021 was not present. All current production inventory_balances rows were
observed with min_stock=0, matching the old server default, and the audit log
contains no evidence of intentional individual threshold overrides. The
reconciliation therefore treats every existing zero as the known stale
baseline and moves it to the intended threshold of five.
"""

from alembic import op
import sqlalchemy as sa

revision = "0025_inventory_min_stock_reconciliation"
down_revision = "0024_bonus_record_source"
branch_labels = None
depends_on = None


def upgrade():
    # Change the schema contract first, then reconcile existing data to it.
    op.alter_column(
        "inventory_balances",
        "min_stock",
        existing_type=sa.Integer(),
        server_default=sa.text("5"),
    )
    op.execute(
        sa.text(
            "UPDATE inventory_balances "
            "SET min_stock = 5 "
            "WHERE min_stock = 0"
        )
    )


def downgrade():
    # Deliberately asymmetric: upgrade fixes production data that was already
    # known to be stale. Reverting those values to 0 would restore the live
    # low-stock alert bug. A downgrade therefore changes only the schema
    # default and leaves reconciled/existing data intact.
    op.alter_column(
        "inventory_balances",
        "min_stock",
        existing_type=sa.Integer(),
        server_default=sa.text("0"),
    )
