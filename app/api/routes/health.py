from fastapi import APIRouter

from app.core.config import get_settings
from app.db.session import check_database_connection

router = APIRouter()


@router.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Report that the NEXORA backend is available."""
    settings = get_settings()
    database_status = check_database_connection()
    return {
        "status": "ok" if database_status != "unavailable" else "degraded",
        "service": settings.app_name,
        "database": database_status,
    }
