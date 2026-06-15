import logging
from typing import Dict, Any, Optional
from datetime import datetime
from bson import ObjectId

from app.repositories.usage_repository import usage_repository
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-usage-service")

class UsageService:
    async def record_compute(
        self,
        project_id: str,
        workspace_id: str,
        user_id: str,
        compute_seconds: int,
        metadata: Optional[Dict[str, Any]] = None
    ):
        event = {
            "type": "compute",
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(workspace_id),
            "user_id": ObjectId(user_id),
            "compute_seconds": compute_seconds,
            "storage_bytes": 0,
            "timestamp": utc_now(),
            "metadata": metadata or {}
        }
        await usage_repository.insert_usage_event(event)

    async def record_storage(
        self,
        project_id: str,
        workspace_id: str,
        user_id: str,
        storage_bytes: int,
        metadata: Optional[Dict[str, Any]] = None
    ):
        event = {
            "type": "storage",
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(workspace_id),
            "user_id": ObjectId(user_id),
            "compute_seconds": 0,
            "storage_bytes": storage_bytes,
            "timestamp": utc_now(),
            "metadata": metadata or {}
        }
        await usage_repository.insert_usage_event(event)
        
    async def record_pipeline_execution(self, project_id: str, workspace_id: str, user_id: str):
        event = {
            "type": "pipeline_execution",
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(workspace_id),
            "user_id": ObjectId(user_id),
            "compute_seconds": 0,
            "storage_bytes": 0,
            "timestamp": utc_now(),
            "metadata": {}
        }
        await usage_repository.insert_usage_event(event)
        
    async def record_report_generation(self, project_id: str, workspace_id: str, user_id: str):
        event = {
            "type": "report_generation",
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(workspace_id),
            "user_id": ObjectId(user_id),
            "compute_seconds": 0,
            "storage_bytes": 0,
            "timestamp": utc_now(),
            "metadata": {}
        }
        await usage_repository.insert_usage_event(event)

usage_service = UsageService()
