import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router, dev
from app.core.config import settings
from app.services import timers
from app.services.orders import OrderError
from app.webhook import router as webhook

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # tests drive the timer directly; everywhere else the loop runs in the background
    task = asyncio.create_task(timers.run_forever()) if settings.ENV != "test" else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(title="WhatsApp AI Order Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(OrderError)
    async def order_error(_: Request, exc: OrderError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    app.include_router(webhook.router)
    # payment QRs and customer screenshots; public so WhatsApp can fetch the QR by link
    settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")
    if settings.ENV in ("dev", "test"):
        app.include_router(dev.router)
    return app


app = create_app()
