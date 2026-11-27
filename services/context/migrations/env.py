"""Alembic entry point. Only the context service schema is managed here."""

import os

from alembic import context
from sqlalchemy import create_engine, pool


def database_url():
    value = context.config.get_main_option("sqlalchemy.url") or os.environ.get("CONTEXT_DATABASE_URL")
    if not value:
        raise RuntimeError("CONTEXT_DATABASE_URL is required for migrations")
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


if context.is_offline_mode():
    context.configure(url=database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    connection = context.config.attributes["connection"]
    context.configure(connection=connection,
                      version_table_schema=connection.exec_driver_sql("SELECT current_schema()").scalar())
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(database_url(), poolclass=pool.NullPool).begin() as connection:
        context.configure(connection=connection,
                          version_table_schema=connection.exec_driver_sql("SELECT current_schema()").scalar())
        with context.begin_transaction():
            context.run_migrations()

