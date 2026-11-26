
import os

from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.orm import declarative_base, sessionmaker

from apps.api.database_safety import (
    DatabaseSafetyError,
    DatabaseTarget,
    validate_database_target,
    verify_test_database_connection,
)

DATABASE_URL = os.getenv("DATABASE_URL")

DATABASE_TARGET: DatabaseTarget = validate_database_target(
    DATABASE_URL,
    os.environ,
)

try:
    engine = create_engine(
        DATABASE_TARGET.url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"check_same_thread": False}
        if DATABASE_TARGET.url.get_backend_name() == "sqlite"
        else {},
    )
except ArgumentError:
    raise DatabaseSafetyError(
        "Database engine configuration is invalid; connection details are suppressed"
    ) from None

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        if DATABASE_TARGET.environment == "test":
            try:
                verify_test_database_connection(db.connection(), DATABASE_TARGET)
            except DBAPIError:
                raise DatabaseSafetyError(
                    "Test database connection failed; connection details are suppressed"
                ) from None
        yield db
    finally:
        db.close()
