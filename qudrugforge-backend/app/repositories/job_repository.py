import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Any
from app.core.metrics import ACTIVE_JOBS, COMPLETED_JOB_COUNT, FAILED_JOB_COUNT, QUEUE_DEPTH

class JobRepository:
    @property
    def collection(self):
        return get_database()["jobs"]

    @property
    def logs_collection(self):
        return get_database()["job_logs"]
        
    @property
    def events_collection(self):
        return get_database()["job_events"]

    async def ensure_indexes(self):
        await self.collection.create_index("project_id")
        await self.collection.create_index("experiment_id")
        await self.collection.create_index("status")
        await self.logs_collection.create_index("job_id")
        await self.events_collection.create_index("job_id")

    async def create_job(self, job_doc: dict) -> dict:
        result = await self.collection.insert_one(job_doc)
        if job_doc.get("status") == "QUEUED":
            QUEUE_DEPTH.inc()
        return await self.get_job_by_id(str(result.inserted_id))

    async def get_job_by_id(self, job_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(job_id):
            return None
        return await self.collection.find_one({"_id": ObjectId(job_id)})

    async def update_job_status(self, job_id: str, status: str, progress: int = None, error_message: str = None) -> Optional[dict]:
        if not ObjectId.is_valid(job_id):
            return None
            
        job = await self.get_job_by_id(job_id)
        if not job:
            return None
            
        previous_status = job.get("status")
            
        update_fields = {"status": status}
        if progress is not None:
            update_fields["progress"] = progress
        if error_message is not None:
            update_fields["error_message"] = error_message
            
        from app.utils.datetime import utc_now
        now = utc_now()
        
        if status == "RUNNING" and not job.get("started_at"):
            update_fields["started_at"] = now
        elif status in ["COMPLETED", "FAILED", "CANCELLED"]:
            update_fields["completed_at"] = now
            started_at = job.get("started_at")
            if started_at:
                if started_at.tzinfo is None:
                    from datetime import timezone
                    started_at = started_at.replace(tzinfo=timezone.utc)
                compute_seconds = int((now - started_at).total_seconds())
                update_fields["compute_seconds"] = compute_seconds
            if previous_status == "RUNNING":
                ACTIVE_JOBS.dec()
            
            job_type = job.get("task_type", "unknown")
            if status == "COMPLETED":
                COMPLETED_JOB_COUNT.labels(job_type=job_type).inc()
            elif status == "FAILED":
                FAILED_JOB_COUNT.labels(job_type=job_type).inc()

        if status == "RUNNING" and previous_status != "RUNNING":
            ACTIVE_JOBS.inc()
            
        if previous_status == "QUEUED" and status != "QUEUED":
            QUEUE_DEPTH.dec()
        elif status == "QUEUED" and previous_status != "QUEUED":
            QUEUE_DEPTH.inc()
            
        await self.collection.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": update_fields}
        )
        
        # Record the lifecycle event
        await self.events_collection.insert_one({
            "job_id": ObjectId(job_id),
            "event_type": "STATE_CHANGE",
            "previous_status": previous_status,
            "new_status": status,
            "timestamp": now,
            "metadata": {"progress": progress, "error_message": error_message}
        })
        
        return await self.get_job_by_id(job_id)

    async def get_job_logs(self, job_id: str, skip: int = 0, limit: int = 100) -> tuple[List[dict], int]:
        if not ObjectId.is_valid(job_id):
            return [], 0
            
        query = {"job_id": ObjectId(job_id)}
        total = await self.logs_collection.count_documents(query)
        cursor = self.logs_collection.find(query).sort("timestamp", pymongo.ASCENDING).skip(skip).limit(limit)
        logs = await cursor.to_list(length=limit)
        
        return logs, total

job_repository = JobRepository()
