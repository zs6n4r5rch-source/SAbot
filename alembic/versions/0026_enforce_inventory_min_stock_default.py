"""enforce inventory minimum stock database default.

The application model and earlier migrations declare a default of five, but
some production/fresh-database paths can leave PostgreSQL without a
pg_attrdef on inventory_balances.min_stock. Make the live database contract
explicit and reconcile legacy zero values at the same time.
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_enforce_inventory_min_stock_default"
down_revision = "0025_inventory_min_stock_reconciliation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            "ALTER TABLE inventory_balances "
            "ALTER COLUMN min_stock SET DEFAULT 5"
        )
    )
    op.execute(
        sa.text(
            "UPDATE inventory_balances "
            "SET min_stock = 5 "
            "WHERE min_stock = 0"
        )
    )


def downgrade():
    op.execute(
        sa.text(
            "ALTER TABLE inventory_balances "
            "ALTER COLUMN min_stock SET DEFAULT 0"
        )
    )
