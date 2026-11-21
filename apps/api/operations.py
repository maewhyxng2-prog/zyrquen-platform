import json
import ipaddress
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.database_safety import verify_test_database_connection


SENSITIVE_NAMES = (
    "authorization",
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "cookie",
    "secret",
)


def redact_sensitive_text(value: Any) -> str:
    text_value = str(value)
    for name in SENSITIVE_NAMES:
        text_value = text_value.replace(name, "[REDACTED]")
        text_value = text_value.replace(name.upper(), "[REDACTED]")
    return text_value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "severity": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
        }
        for name in (
            "correlation_id",
            "method",
            "route",
            "status_code",
            "duration_ms",
        ):
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        if record.exc_info:
            payload["exception"] = redact_sensitive_text(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False)


def database_readiness(engine, target) -> dict:
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1").close()
            if target.environment == "test":
                verify_test_database_connection(connection, target)
        return {"status": "healthy", "database": "available"}
    except Exception:
        return {"status": "unavailable", "database": "unavailable"}


def aggregate_readiness(database_status: dict, runtime_status: dict) -> dict:
    database_state = database_status["status"]
    native_state = runtime_status["runtime_status"]

    if database_state == "healthy" and native_state == "ready":
        return {
            "status": "healthy",
            "database": database_status,
            "native_ai": runtime_status,
        }

    if database_state == "healthy" and native_state == "not_configured":
        return {
            "status": "degraded",
            "database": database_status,
            "native_ai": runtime_status,
        }

    if database_state == "healthy":
        return {
            "status": "degraded",
            "database": database_status,
            "native_ai": runtime_status,
        }

    return {
        "status": "unavailable",
        "database": database_status,
        "native_ai": runtime_status,
    }


def validate_security_configuration(environment: str) -> None:
    if environment != "production":
        return

    secret = os.getenv("JWT_SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "Production startup rejected: JWT_SECRET_KEY is not configured"
        )
    if len(secret) < 32:
        raise RuntimeError(
            "Production startup rejected: JWT_SECRET_KEY is too short"
        )

    origins = {
        origin.strip()
        for origin in os.getenv("ZYRQUEN_CORS_ALLOW_ORIGINS", "").split(",")
        if origin.strip()
    }
    if "*" in origins:
        raise RuntimeError(
            "Production startup rejected: wildcard CORS origin is not allowed"
        )

    try:
        for value in os.getenv("ZYRQUEN_TRUSTED_PROXY_IPS", "").split(","):
            if value.strip():
                ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        raise RuntimeError(
            "Production startup rejected: trusted proxy allowlist is invalid"
        ) from None


def install_exception_logging(app) -> None:
    @app.exception_handler(Exception)
    async def unhandled_exception(request, exc):
        correlation_id = getattr(request.state, "correlation_id", None)
        logger = logging.getLogger("zyrquen.exception")
        logger.exception(
            "Unhandled request exception",
            extra={"correlation_id": correlation_id or "unknown"},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
