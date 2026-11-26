"""Fail-closed database target validation for runtime and migrations."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.engine import Connection, URL, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError


class DatabaseSafetyError(RuntimeError):
    """Raised when a database target cannot be proven safe for its environment."""


@dataclass(frozen=True)
class DatabaseTarget:
    url: URL
    environment: str
    database_name: str
    test_database_id: str | None = None


def _required_value(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise DatabaseSafetyError(
            f"Database target rejected: required setting {name} is missing"
        )
    return value


def _normalized_host(value: str) -> str:
    return value.strip().lower().rstrip(".")


def _csv_values(environment: Mapping[str, str], name: str) -> set[str]:
    values = {
        value.strip().lower().rstrip(".")
        for value in _required_value(environment, name).split(",")
        if value.strip()
    }
    if not values:
        raise DatabaseSafetyError(
            f"Database target rejected: required setting {name} has no entries"
        )
    return values


def _require_target(
    url: URL,
    environment: Mapping[str, str],
    *,
    expected_host_setting: str,
    expected_name_setting: str,
    expected_port_setting: str,
) -> None:
    host = _normalized_host(url.host or "")
    database_name = url.database or ""
    try:
        port = 5432 if url.port is None else url.port
        expected_port = int(_required_value(environment, expected_port_setting))
    except (ValueError, ArgumentError):
        raise DatabaseSafetyError(
            "Database target rejected: approved database port is invalid"
        ) from None
    if not 1 <= port <= 65535 or not 1 <= expected_port <= 65535:
        raise DatabaseSafetyError(
            "Database target rejected: approved database port is invalid"
        )
    expected_host = _normalized_host(
        _required_value(environment, expected_host_setting)
    )
    expected_name = _required_value(environment, expected_name_setting)

    if (
        not host
        or host != expected_host
        or port != expected_port
        or database_name != expected_name
    ):
        raise DatabaseSafetyError(
            "Database target rejected: URL does not match the approved environment target"
        )


def _reject_production_target(url: URL, environment: Mapping[str, str]) -> None:
    host = _normalized_host(url.host or "")
    database_name = (url.database or "").lower()
    production_hosts = _csv_values(
        environment,
        "ZYRQUEN_PRODUCTION_DATABASE_HOSTS",
    )
    production_names = _csv_values(
        environment,
        "ZYRQUEN_PRODUCTION_DATABASE_NAMES",
    )

    if host in production_hosts or database_name.lower() in production_names:
        raise DatabaseSafetyError(
            "Database target rejected: Test target matches a protected Production target"
        )


def validate_database_target(
    database_url: str | None,
    environment: Mapping[str, str],
    *,
    for_migration: bool = False,
) -> DatabaseTarget:
    """Validate a URL and its declared target before constructing an engine."""
    environment_name = environment.get("ZYRQUEN_ENV", "").strip().lower()
    supported_environments = {"development", "production", "test", "unit_test"}
    if environment_name not in supported_environments:
        raise DatabaseSafetyError(
            "Database target rejected: ZYRQUEN_ENV is missing or unrecognized"
        )

    if for_migration and environment_name != "test":
        raise DatabaseSafetyError(
            "Migration rejected: Alembic is permitted only for the Test environment"
        )

    if not database_url:
        raise DatabaseSafetyError("Database target rejected: DATABASE_URL is missing")

    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError):
        raise DatabaseSafetyError(
            "Database target rejected: DATABASE_URL is invalid"
        ) from None

    if environment_name == "unit_test":
        if for_migration or url.get_backend_name() != "sqlite":
            raise DatabaseSafetyError(
                "Database target rejected: unit_test permits SQLite runtime tests only"
            )
        return DatabaseTarget(
            url=url,
            environment=environment_name,
            database_name=url.database or "",
        )

    if url.drivername != "postgresql+psycopg":
        raise DatabaseSafetyError(
            "Database target rejected: only PostgreSQL with psycopg is supported"
        )

    routing_query_keys = {
        "host",
        "hostaddr",
        "port",
        "dbname",
        "service",
        "servicefile",
    }
    if any(key.lower() in routing_query_keys for key in url.query):
        raise DatabaseSafetyError(
            "Database target rejected: URL contains an alternate routing setting"
        )
    if environment.get("PGHOSTADDR") or environment.get("PGSERVICE"):
        raise DatabaseSafetyError(
            "Database target rejected: libpq contains an alternate routing setting"
        )

    if environment_name == "test":
        _reject_production_target(url, environment)
        _require_target(
            url,
            environment,
            expected_host_setting="ZYRQUEN_TEST_DATABASE_HOST",
            expected_name_setting="ZYRQUEN_TEST_DATABASE_NAME",
            expected_port_setting="ZYRQUEN_TEST_DATABASE_PORT",
        )
        test_database_id = _required_value(
            environment,
            "ZYRQUEN_TEST_DATABASE_ID",
        )
        return DatabaseTarget(
            url=url,
            environment=environment_name,
            database_name=url.database or "",
            test_database_id=test_database_id,
        )

    if environment_name == "development":
        _require_target(
            url,
            environment,
            expected_host_setting="ZYRQUEN_DEVELOPMENT_DATABASE_HOST",
            expected_name_setting="ZYRQUEN_DEVELOPMENT_DATABASE_NAME",
            expected_port_setting="ZYRQUEN_DEVELOPMENT_DATABASE_PORT",
        )
        return DatabaseTarget(
            url=url,
            environment=environment_name,
            database_name=url.database or "",
        )

    _require_target(
        url,
        environment,
        expected_host_setting="ZYRQUEN_PRODUCTION_DATABASE_HOST",
        expected_name_setting="ZYRQUEN_PRODUCTION_DATABASE_NAME",
        expected_port_setting="ZYRQUEN_PRODUCTION_DATABASE_PORT",
    )
    return DatabaseTarget(
        url=url,
        environment=environment_name,
        database_name=url.database or "",
    )


def verify_test_database_identity_rows(
    rows: Sequence[Sequence[object]],
    *,
    expected_database_name: str,
    expected_database_id: str,
) -> None:
    """Require the read-only identity record installed by the Test DB operator."""
    if len(rows) != 1 or len(rows[0]) != 3:
        raise DatabaseSafetyError(
            "Database target rejected: Test database identity is missing or ambiguous"
        )

    database_name, database_environment, database_id = rows[0]
    if (
        database_name != expected_database_name
        or database_environment != "test"
        or database_id != expected_database_id
    ):
        raise DatabaseSafetyError(
            "Database target rejected: connected database identity does not match Test"
        )


def verify_test_database_connection(
    connection: Connection,
    target: DatabaseTarget,
) -> None:
    if target.environment != "test" or not target.test_database_id:
        raise DatabaseSafetyError(
            "Database target rejected: Test identity verification is not configured"
        )

    try:
        result = connection.exec_driver_sql(
            "SELECT current_database(), environment, database_id "
            "FROM public.zyrquen_environment_identity"
        )
        rows = result.fetchall()
        result.close()
    except DBAPIError:
        raise DatabaseSafetyError(
            "Database target rejected: Test database identity could not be read"
        ) from None

    verify_test_database_identity_rows(
        rows,
        expected_database_name=target.database_name,
        expected_database_id=target.test_database_id,
    )
