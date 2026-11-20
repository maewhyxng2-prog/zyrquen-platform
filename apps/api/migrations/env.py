import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.pool import NullPool

config = context.config
if config.config_file_name and config.get_section("loggers"):
    fileConfig(config.config_file_name)

api_dir = Path(__file__).resolve().parents[1]
repository_root = api_dir.parents[1]
sys.path.insert(0, str(api_dir))
sys.path.insert(0, str(repository_root))

from apps.api.database import Base  # noqa: E402
from apps.api.database_safety import (  # noqa: E402
    DatabaseTarget,
    validate_database_target,
    verify_test_database_connection,
)
import apps.api.models  # noqa: E402,F401
import apps.api.training_models  # noqa: E402,F401
import apps.api.evaluation_models  # noqa: E402,F401
import apps.api.usage_models  # noqa: E402,F401
import apps.api.api_access_models  # noqa: E402,F401

target_metadata = Base.metadata


def migration_target() -> DatabaseTarget:
    return validate_database_target(
        os.getenv("DATABASE_URL"),
        os.environ,
        for_migration=True,
    )


def run_migrations_online() -> None:
    target = migration_target()
    try:
        connectable = create_engine(
            target.url,
            poolclass=pool.NullPool,
            hide_parameters=True,
        )
    except ArgumentError:
        raise RuntimeError(
            "Test database engine configuration is invalid; "
            "connection details are suppressed"
        ) from None
    try:
        connection = connectable.connect()
    except DBAPIError:
        raise RuntimeError(
            "Test database connection failed; connection details are suppressed"
        ) from None

    with connection:
        verify_test_database_connection(connection, target)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline migrations are disabled because the Test database identity "
        "cannot be verified."
    )

run_migrations_online()
