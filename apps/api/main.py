
from fastapi import FastAPI

from routers.auth import router as auth_router

app = FastAPI(
    title="ZYRQUEN Ω∞ API",
    version="0.1.0",
)

app.include_router(auth_router)


@app.get("/")
async def root():
    return {
        "platform": "ZYRQUEN Ω∞",
        "status": "running",
        "mode": "online",
        "native_ai": "not_implemented",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "zyrquen-api",
    }
