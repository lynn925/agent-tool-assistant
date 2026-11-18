"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe used by frontend / CI."""
    return {"status": "ok"}
