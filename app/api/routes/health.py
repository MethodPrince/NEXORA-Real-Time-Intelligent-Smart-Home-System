from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Report that the NEXORA backend is available."""
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name}
