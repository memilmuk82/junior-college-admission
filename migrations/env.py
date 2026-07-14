from __future__ import annotations

from logging import getLogger
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401
from app import _environment_value
from app.database import Base

config = context.config
logger = getLogger("alembic.env")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = _environment_value("DATABASE_URL")
if not database_url:
    raise RuntimeError("Alembic 실행에는 PostgreSQL DATABASE_URL 환경 변수가 필요합니다.")
if not database_url.startswith("postgresql+"):
    raise RuntimeError("Alembic은 PostgreSQL DATABASE_URL만 허용합니다.")
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def process_revision_directives(
    _migration_context: object, _revision: object, directives: list[Any]
) -> None:
    if not getattr(config.cmd_opts, "autogenerate", False):
        return
    script = directives[0]
    if script.upgrade_ops.is_empty():
        directives[:] = []
        logger.info("No changes in schema detected.")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        process_revision_directives=process_revision_directives,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            process_revision_directives=process_revision_directives,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
