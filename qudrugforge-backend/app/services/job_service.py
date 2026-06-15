from typing import List, Dict, Any, Optional
from bson import ObjectId
from app.core.exceptions import AppException
from app.repositories.job_repository import job_repository

class JobService:
    async def get_job(self, job_id: str) -> dict:
        job = await job_repository.get_job_by_id(job_id)
        if not job:
            raise AppException(
                status_code=404,
                code="JOB_NOT_FOUND",
                message=f"Job {job_id} not found."
            )
        return job

    async def cancel_job(self, job_id: str) -> dict:
        job = await self.get_job(job_id)
        if job["status"] in ["COMPLETED", "FAILED", "CANCELLED"]:
            raise AppException(
                status_code=400,
                code="INVALID_JOB_STATE",
                message=f"Job {job_id} is already in a terminal state ({job['status']})."
            )
            
        # In the future, this will also send a revoke command to Celery
        updated_job = await job_repository.update_job_status(job_id, "CANCELLED", error_message="Job was cancelled by user.")
        return updated_job

    async def get_job_logs(self, job_id: str, limit: int = 100, skip: int = 0) -> tuple[List[dict], int]:
        await self.get_job(job_id) # ensure it exists
        return await job_repository.get_job_logs(job_id, skip=skip, limit=limit)

job_service = JobService()
