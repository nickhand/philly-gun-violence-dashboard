"""FastAPI application setup for the Gun Violence Dashboard API."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from loguru import logger

from app.data_loader import (
    init_dataset_keys,
    load_boundary_data,
    load_homicides_data,
    load_shootings_data,
    load_streets_data,
)
from app.routers.boundaries import router as boundaries_router
from app.routers.health import router as health_router
from app.routers.homicides import router as homicides_router
from app.routers.meta import router as meta_router
from app.routers.shootings import router as shootings_router
from app.routers.streets import router as streets_router
from dashboard_utils.aws import make_s3_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load S3-backed datasets into application state on startup.

    Parameters
    ----------
    app : fastapi.FastAPI
        The FastAPI application instance.

    Yields
    ------
    None
        Control back to FastAPI for request handling.
    """
    startup_start = time.perf_counter()
    logger.info("Starting API initialization...")

    # Initialize shared clients and load cached datasets once at startup.
    s3_start = time.perf_counter()
    app.state.s3 = make_s3_client()
    logger.info(f"S3 client created in {(time.perf_counter() - s3_start) * 1000:.1f}ms")

    init_dataset_keys(app)

    shootings_start = time.perf_counter()
    load_shootings_data(app)
    logger.info(f"Shootings data loaded in {(time.perf_counter() - shootings_start) * 1000:.1f}ms")

    boundaries_start = time.perf_counter()
    load_boundary_data(app)
    logger.info(
        f"Boundaries data loaded in {(time.perf_counter() - boundaries_start) * 1000:.1f}ms"
    )

    streets_start = time.perf_counter()
    load_streets_data(app)
    logger.info(f"Streets data loaded in {(time.perf_counter() - streets_start) * 1000:.1f}ms")

    homicides_start = time.perf_counter()
    load_homicides_data(app)
    logger.info(f"Homicides data loaded in {(time.perf_counter() - homicides_start) * 1000:.1f}ms")

    total_time = (time.perf_counter() - startup_start) * 1000
    logger.info(f"API initialization complete in {total_time:.1f}ms")
    yield


app = FastAPI(
    title="Gun Violence Dashboard API",
    version="0.1.0",
    lifespan=lifespan,
)

# Add GZip compression for responses >= 1000 bytes
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://phillygunviolence.netlify.app",
        "https://www.nickhand.dev",
        "https://nickhand.dev",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(shootings_router)
app.include_router(boundaries_router)
app.include_router(streets_router)
app.include_router(homicides_router)
app.include_router(meta_router)
app.include_router(health_router)
