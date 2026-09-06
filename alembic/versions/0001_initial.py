"""initial application schema"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Keep migration generated from the application models but explicit so a fresh DB is reproducible.
    from app.models import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[
        Base.metadata.tables[name] for name in [
            "clubs", "employees", "employee_clubs", "telegram_users", "shifts",
            "product_categories", "products", "langame_sync_log", "stock_snapshots",
            "inventory_balances", "inventory_operations", "writeoff_reasons", "writeoffs",
            "writeoff_items", "inventories", "inventory_items", "discrepancies",
            "salary_rules", "salary_periods", "salary_adjustments", "salary_payments",
            "analytics_daily", "analytics_product_daily", "analytics_employee_daily",
        ]
    ])


def downgrade():
    from app.models import Base
    bind = op.get_bind()
    for name in reversed([
        "analytics_employee_daily", "analytics_product_daily", "analytics_daily",
        "salary_payments", "salary_adjustments", "salary_periods", "salary_rules",
        "discrepancies", "inventory_items", "inventories", "writeoff_items", "writeoffs",
        "writeoff_reasons", "inventory_operations", "inventory_balances", "stock_snapshots",
        "langame_sync_log", "products", "product_categories", "shifts", "telegram_users",
        "employee_clubs", "employees", "clubs",
    ]):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
