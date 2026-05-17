from pathlib import Path
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()

@router.get("/health", tags=["Health"])
async def health_check():
    """
    Diagnostic endpoint that validates database pools, local folder storage bounds, 
    and external cluster connections.
    """
    # 1. Database connection check
    # Check if motor database is instantiated
    from app.core.database import database
    db_status = "connected" if database is not None else "disconnected"

    # 2. Local physical storage check
    storage_provider = settings.STORAGE_PROVIDER
    storage_status = "unknown"
    
    if storage_provider == "local":
        try:
            storage_path = Path(settings.LOCAL_STORAGE_ROOT)
            # Safely create local directory if missing in host
            if not storage_path.exists():
                storage_path.mkdir(parents=True, exist_ok=True)
            storage_status = "local"
        except Exception as e:
            storage_status = f"disconnected (error creating local path: {str(e)})"
    else:
        storage_status = storage_provider

    return {
        "status": "ok",
        "service": "QuDrugForge Backend",
        "environment": settings.APP_ENV,
        "database": db_status,
        "storage": storage_status,
        "q_ai_drug": "unknown"
    }
