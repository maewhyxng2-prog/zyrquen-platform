
import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.routers.auth import router as auth_router
from apps.api.routers.inference import router as inference_router
from apps.api.routers.training import router as training_router
from apps.api.routers.datasets import router as datasets_router
from apps.api.routers.evaluation import router as evaluation_router
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.users import router as users_router
from apps.api.routers.usage import router as usage_router
from apps.api.routers.api_access import router as api_access_router
from apps.api.routers.admin import router as admin_router
from apps.api.routers.workflows import get_workflow_engine, router as workflows_router
from apps.api import api_access_models  # noqa: F401
from apps.api import usage_models  # noqa: F401
from apps.api import workflow_models  # noqa: F401

from apps.core.runtime import runtime
from apps.api.database import DATABASE_TARGET, engine
from apps.api.operations import (
    JsonFormatter,
    aggregate_readiness,
    database_readiness,
    install_exception_logging,
    redact_sensitive_text,
    validate_security_configuration,
)

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)


def _validate_startup_configuration() -> None:
    environment = os.getenv("ZYRQUEN_ENV", "").strip().lower()
    validate_security_configuration(environment)


class CorrelationAndObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        correlation_id = (
            request.headers.get("x-correlation-id")
            or request.headers.get("x-request-id")
            or str(uuid.uuid4())
        )
        correlation_id = correlation_id[:128]
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = message.setdefault("headers", [])
                headers.extend([
                    (b"x-correlation-id", correlation_id.encode("ascii", "replace")),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                ])
                if os.getenv("ZYRQUEN_ENV", "").strip().lower() == "production":
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            route = scope.get("route")
            route_template = getattr(route, "path", None) or scope.get("path", "")
            logger.info(
                "http_request",
                extra={
                    "correlation_id": correlation_id,
                    "method": scope.get("method", ""),
                    "route": redact_sensitive_text(route_template),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    _validate_startup_configuration()
    ready = await asyncio.to_thread(runtime.initialize)

    if ready:
        logger.info("ZYRQUEN Native AI Runtime is ready")
    else:
        logger.warning(
            "ZYRQUEN API started, but Native AI Model is unavailable"
        )

    workflow_engine = get_workflow_engine()
    workflow_engine.start(
        enable_scheduler=os.getenv("ZYRQUEN_WORKFLOW_SCHEDULER", "1").strip() != "0",
        enable_recovery=os.getenv("ZYRQUEN_WORKFLOW_RECOVERY", "1").strip() != "0",
    )

    yield

    workflow_engine.shutdown()
    runtime.shutdown()
    engine.dispose()


app = FastAPI(
    title="ZYRQUEN Ω∞ API",
    version="0.3.0",
    lifespan=lifespan,
)

cors_origins = [
    origin.strip()
    for origin in os.getenv("ZYRQUEN_CORS_ALLOW_ORIGINS", "").split(",")
    if origin.strip()
]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID", "X-Request-ID"],
    )

app.add_middleware(CorrelationAndObservabilityMiddleware)
install_exception_logging(app)

app.include_router(auth_router)
app.include_router(inference_router)
app.include_router(training_router)
app.include_router(datasets_router)
app.include_router(evaluation_router)
app.include_router(conversations_router)
app.include_router(users_router)
app.include_router(usage_router)
app.include_router(api_access_router)
app.include_router(admin_router)
app.include_router(workflows_router)


@app.get("/")
async def root():
    return {
        "platform": "ZYRQUEN Ω∞",
        "status": "running",
        "mode": "online",
        "native_ai": runtime.get_health_status(),
    }


@app.get("/health")
async def health():
    database = database_readiness(engine, DATABASE_TARGET)
    native_ai = runtime.get_health_status()
    readiness = aggregate_readiness(database, native_ai)
    status_code = 200 if readiness["status"] == "healthy" else 503
    return JSONResponse(status_code=status_code, content={
        "status": readiness["status"],
        "service": "zyrquen-api",
        "database": database,
        "native_ai": native_ai,
    })


@app.get("/livez")
async def liveness():
    """Liveness indicates only that the API process can answer requests."""
    return {"status": "healthy", "service": "zyrquen-api"}


@app.get("/readyz")
async def readiness():
    database = database_readiness(engine, DATABASE_TARGET)
    native_ai = runtime.get_health_status()
    result = aggregate_readiness(database, native_ai)
    status_code = 200 if result["status"] == "healthy" else 503
    return JSONResponse(status_code=status_code, content=result)


@app.get("/v1/workflows/services/status")
async def workflow_services_status():
    """Return current runtime status of Workflow Scheduler and Recovery services for diagnostics."""
    workflow_engine = get_workflow_engine()
    return workflow_engine.get_service_status()
