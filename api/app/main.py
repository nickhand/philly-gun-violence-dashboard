"""FastAPI application setup for the Gun Violence Dashboard API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    # Initialize shared clients and load cached datasets once at startup.
    app.state.s3 = make_s3_client()
    init_dataset_keys(app)
    load_shootings_data(app)
    load_boundary_data(app)
    load_streets_data(app)
    load_homicides_data(app)
    yield


app = FastAPI(
    title="Gun Violence Dashboard API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://phillygunviolence.netlify.app",
        "https://www.nickhand.dev",
        "https://nickhand.dev",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
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
