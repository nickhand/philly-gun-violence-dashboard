"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Return a simple health status payload.

    Returns
    -------
    dict[str, str]
        The status payload.
    """
    return {"status": "ok"}
