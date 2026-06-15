from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime

class JobLogResponse(BaseModel):
    id: str
    job_id: str
    level: str
    message: str
    timestamp: datetime
    
    @classmethod
    def from_mongo(cls, doc: dict):
        return cls(
            id=str(doc["_id"]),
            job_id=str(doc["job_id"]),
            level=doc.get("level", "info"),
            message=doc["message"],
            timestamp=doc["timestamp"]
        )

class JobResponse(BaseModel):
    id: str
    project_id: str
    experiment_id: Optional[str] = None
    task_type: str
    status: str
    progress: int
    error_message: Optional[str] = None
    retries_attempted: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @classmethod
    def from_mongo(cls, doc: dict):
        return cls(
            id=str(doc["_id"]),
            project_id=str(doc["project_id"]),
            experiment_id=str(doc.get("experiment_id")) if doc.get("experiment_id") else None,
            task_type=doc["task_type"],
            status=doc["status"],
            progress=doc.get("progress", 0),
            error_message=doc.get("error_message"),
            retries_attempted=doc.get("retries_attempted", 0),
            created_at=doc["created_at"],
            started_at=doc.get("started_at"),
            completed_at=doc.get("completed_at")
        )
