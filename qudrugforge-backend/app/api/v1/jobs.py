from fastapi import APIRouter, Depends, Path, Query
from app.schemas.job import JobResponse, JobLogResponse
from app.services.job_service import job_service
from app.core.dependencies import get_current_active_user
from app.core.rate_limit import limiter
from app.core.config import settings
from fastapi import Request

router = APIRouter(prefix="/jobs", tags=["Jobs"])

@router.get("/{job_id}")
async def get_job(
    job_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    job = await job_service.get_job(job_id)
    return {
        "success": True,
        "data": JobResponse.from_mongo(job).model_dump(),
        "message": "Job fetched successfully"
    }

@router.post("/{job_id}/cancel")
@limiter.limit(settings.RATE_LIMIT_PIPELINE)
async def cancel_job(
    request: Request,
    job_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    job = await job_service.cancel_job(job_id)
    return {
        "success": True,
        "data": JobResponse.from_mongo(job).model_dump(),
        "message": "Job cancelled successfully"
    }

@router.get("/{job_id}/logs")
async def get_job_logs(
    job_id: str = Path(...),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    logs, total = await job_service.get_job_logs(job_id, limit=limit, skip=offset)
    return {
        "success": True,
        "data": {
            "items": [JobLogResponse.from_mongo(log).model_dump() for log in logs],
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Job logs fetched successfully"
    }
