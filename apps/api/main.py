
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from routers.auth import router as auth_router
from routers.inference import router as inference_router
from routers.training import router as training_router
from apps.core.runtime import runtime

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ready = await asyncio.to_thread(runtime.initialize)

    if ready:
        logger.info("ZYRQUEN Native AI Runtime is ready")
    else:
        logger.warning(
            "ZYRQUEN API started, but Native AI Model is unavailable"
        )

    yield


app = FastAPI(
    title="ZYRQUEN Ω∞ API",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(inference_router)
app.include_router(training_router)


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
    return {
        "status": "healthy",
        "service": "zyrquen-api",
        "native_ai": runtime.get_health_status(),
    }
