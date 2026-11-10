import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from bot_social import models  # noqa: F401
from bot_social.db import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option(
    "sqlalchemy.url", os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
)
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # These PostgreSQL expression indexes are managed by a hand-written migration.
    if type_ == "index" and name in {"ix_cases_claim_fts", "ix_evidence_passage_fts"}:
        return False
    return True


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_object=include_object
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
