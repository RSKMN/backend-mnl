from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()

@router.get("/system/info", tags=["System"])
async def system_info():
    """
    Exposes platform runtime settings and active compute URLs without revealing
    confidential connection strings or database credentials.
    """
    return {
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "debug": settings.APP_DEBUG,
        "api_prefix": settings.API_V1_PREFIX,
        "storage_provider": settings.STORAGE_PROVIDER,
        "local_storage_root": settings.LOCAL_STORAGE_ROOT,
        "q_ai_drug_base_url": settings.Q_AI_DRUG_BASE_URL,
        "mongodb_database": settings.MONGODB_DATABASE
    }
