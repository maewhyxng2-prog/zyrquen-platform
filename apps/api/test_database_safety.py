import pytest

from apps.api.database_safety import (
    DatabaseSafetyError,
    validate_database_target,
    verify_test_database_identity_rows,
)


def _test_environment():
    return {
        "ZYRQUEN_ENV": "test",
        "ZYRQUEN_TEST_DATABASE_HOST": "test-db.example.internal",
        "ZYRQUEN_TEST_DATABASE_PORT": "5432",
        "ZYRQUEN_TEST_DATABASE_NAME": "zyrquen_test",
        "ZYRQUEN_TEST_DATABASE_ID": "test-instance-01",
        "ZYRQUEN_PRODUCTION_DATABASE_HOSTS": "prod-db.example.internal",
        "ZYRQUEN_PRODUCTION_DATABASE_NAMES": "zyrquen",
    }


def test_preflight_accepts_only_the_pinned_test_target():
    target = validate_database_target(
        "postgresql+psycopg://test-db.example.internal/zyrquen_test",
        _test_environment(),
        for_migration=True,
    )

    assert target.environment == "test"
    assert target.database_name == "zyrquen_test"
    assert target.test_database_id == "test-instance-01"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://prod-db.example.internal/zyrquen_test",
        "postgresql+psycopg://test-db.example.internal/zyrquen",
        "postgresql+psycopg://test-db.example.internal:5433/zyrquen_test",
        "postgresql+psycopg://unknown-db.example.internal/zyrquen_test",
        "postgresql+psycopg://test-db.example.internal/zyrquen_test?hostaddr=192.0.2.1",
    ],
)
def test_preflight_rejects_production_and_unclassified_targets(url):
    with pytest.raises(DatabaseSafetyError):
        validate_database_target(url, _test_environment(), for_migration=True)


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"ZYRQUEN_ENV": "staging"},
        {
            "ZYRQUEN_ENV": "test",
            "ZYRQUEN_TEST_DATABASE_HOST": "test-db.example.internal",
        },
    ],
)
def test_preflight_rejects_missing_or_incomplete_environment(environment):
    with pytest.raises(DatabaseSafetyError):
        validate_database_target(
            "postgresql+psycopg://test-db.example.internal/zyrquen_test",
            environment,
            for_migration=True,
        )


def test_preflight_rejects_empty_production_deny_lists():
    environment = _test_environment()
    environment["ZYRQUEN_PRODUCTION_DATABASE_HOSTS"] = " , "

    with pytest.raises(DatabaseSafetyError):
        validate_database_target(
            "postgresql+psycopg://test-db.example.internal/zyrquen_test",
            environment,
            for_migration=True,
        )


def test_preflight_rejects_libpq_host_override():
    environment = _test_environment()
    environment["PGHOSTADDR"] = "192.0.2.1"

    with pytest.raises(DatabaseSafetyError):
        validate_database_target(
            "postgresql+psycopg://test-db.example.internal/zyrquen_test",
            environment,
            for_migration=True,
        )


def test_preflight_error_does_not_echo_malformed_connection_string():
    connection_string = "contains-secret-credential-but-is-not-a-url"

    with pytest.raises(DatabaseSafetyError) as error:
        validate_database_target(
            connection_string,
            _test_environment(),
            for_migration=True,
        )

    assert connection_string not in str(error.value)


@pytest.mark.parametrize("environment_name", ["development", "production", "unit_test"])
def test_alembic_rejects_non_test_environments(environment_name):
    environment = _test_environment()
    environment["ZYRQUEN_ENV"] = environment_name

    with pytest.raises(DatabaseSafetyError):
        validate_database_target(
            "postgresql+psycopg://test-db.example.internal/zyrquen_test",
            environment,
            for_migration=True,
        )


def test_unit_test_allows_sqlite_only_for_runtime_tests():
    target = validate_database_target(
        "sqlite:///./unit-test.db",
        {"ZYRQUEN_ENV": "unit_test"},
    )

    assert target.environment == "unit_test"
    assert target.url.get_backend_name() == "sqlite"


def test_database_identity_must_match_test_target():
    verify_test_database_identity_rows(
        [("zyrquen_test", "test", "test-instance-01")],
        expected_database_name="zyrquen_test",
        expected_database_id="test-instance-01",
    )

    with pytest.raises(DatabaseSafetyError):
        verify_test_database_identity_rows(
            [("zyrquen", "production", "prod-instance")],
            expected_database_name="zyrquen_test",
            expected_database_id="test-instance-01",
        )


def test_database_identity_must_be_unambiguous():
    with pytest.raises(DatabaseSafetyError):
        verify_test_database_identity_rows(
            [],
            expected_database_name="zyrquen_test",
            expected_database_id="test-instance-01",
        )

    with pytest.raises(DatabaseSafetyError):
        verify_test_database_identity_rows(
            [
                ("zyrquen_test", "test", "test-instance-01"),
                ("zyrquen_test", "test", "test-instance-01"),
            ],
            expected_database_name="zyrquen_test",
            expected_database_id="test-instance-01",
        )
