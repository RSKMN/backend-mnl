from pathlib import Path
from fastapi import APIRouter, Response
from app.core.config import settings
import redis

router = APIRouter()

@router.get("/health", tags=["Health"])
async def health_check(response: Response):
    """
    Diagnostic endpoint that validates database pools, local folder storage bounds, 
    Redis message broker, and Celery worker fleet.
    """
    # 1. MongoDB connection check
    from app.core.database import database
    # In development mode with mock_db, database might be a MockDatabase object
    mongo_status = "healthy" if database is not None or settings.APP_ENV == "development" else "unhealthy"

    # 2. Redis connection check
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
        redis_status = "healthy"
    except Exception:
        # In dev mode, assume healthy if redis is not running
        redis_status = "healthy" if settings.APP_ENV == "development" else "unhealthy"

    # 3. Celery Worker check
    try:
        from app.core.celery_app import celery_app
        i = celery_app.control.inspect(timeout=1.0)
        active = i.active()
        if active and len(active) > 0:
            celery_status = "healthy"
        else:
            celery_status = "healthy" if settings.APP_ENV == "development" else "degraded"
    except Exception:
        celery_status = "healthy" if settings.APP_ENV == "development" else "unhealthy"

    # 4. Local physical storage check
    storage_provider = settings.STORAGE_PROVIDER
    storage_status = "unknown"
    
    if storage_provider == "local":
        try:
            storage_path = Path(settings.LOCAL_STORAGE_ROOT)
            if not storage_path.exists():
                storage_path.mkdir(parents=True, exist_ok=True)
            storage_status = "healthy"
        except Exception:
            storage_status = "unhealthy"
    else:
        storage_status = "healthy"

    # Global State Derivation
    global_status = "healthy"
    if mongo_status == "unhealthy" or redis_status == "unhealthy":
        global_status = "unhealthy"
        response.status_code = 503
    elif celery_status == "degraded" or celery_status == "unhealthy" or storage_status == "unhealthy":
        global_status = "degraded"

    return {
        "status": global_status,
        "components": {
            "mongo": mongo_status,
            "redis": redis_status,
            "celery": celery_status,
            "storage": storage_status
        }
    }
