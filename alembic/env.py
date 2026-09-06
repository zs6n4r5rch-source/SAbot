from logging.config import fileConfig
import asyncio
import logging
import os

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def _tx_diag(connection: Connection, label: str) -> None:
    if os.getenv("SABOT_ALEMBIC_TX_DIAG") != "1":
        return
    tx = connection.get_transaction()
    print(f"ALEMBIC_TX {label}: in_transaction={connection.in_transaction()} tx_type={type(tx).__name__ if tx is not None else 'None'} tx_id={id(tx) if tx is not None else None}", flush=True)


def _install_tx_log_filter() -> None:
    if os.getenv("SABOT_ALEMBIC_TX_DIAG") != "1":
        return
    logger = logging.getLogger("sqlalchemy.engine")
    class TxOnlyFilter(logging.Filter):
        def filter(self, record):
            return any(kw in record.getMessage() for kw in ("BEGIN", "COMMIT", "ROLLBACK"))
    logger.setLevel(logging.INFO)
    logger.addFilter(TxOnlyFilter())


def do_run_migrations(connection: Connection):
    _install_tx_log_filter()
    _tx_diag(connection, "after connect")
    connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(255) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"))
    _tx_diag(connection, "after version CREATE")
    connection.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"))
    _tx_diag(connection, "after version ALTER")
    context.configure(connection=connection, target_metadata=target_metadata)
    _tx_diag(connection, "before context.begin_transaction")
    with context.begin_transaction():
        _tx_diag(connection, "inside context.begin_transaction")
        context.run_migrations()
        _tx_diag(connection, "after context.run_migrations")
    _tx_diag(connection, "after context.begin_transaction")


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
