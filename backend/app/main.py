"""FastAPI application entry point for the Silicone Mold Generator."""

from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_mold import router as mold_router
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Ensure working directories exist on startup and clean temporary artifacts on shutdown."""
    settings.ensure_directories()
    logger.info("Directorio de trabajo inicializado: %s", settings.work_dir)
    yield
    if settings.work_dir.exists():
        shutil.rmtree(settings.work_dir, ignore_errors=True)
        logger.info("Directorio temporal limpiado al cerrar: %s", settings.work_dir)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(mold_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
