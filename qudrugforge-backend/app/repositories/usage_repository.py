import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from bson import ObjectId

from app.core.database import get_database
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-usage-repo")

class UsageRepository:
    def __init__(self):
        self._collection_name = "usage_metrics"

    @property
    def collection(self):
        return get_database()[self._collection_name]

    async def insert_usage_event(self, event_doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record a usage event (e.g. compute consumed, storage imported).
        """
        result = await self.collection.insert_one(event_doc)
        event_doc["_id"] = result.inserted_id
        return event_doc

    async def aggregate_usage(
        self,
        workspace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        match = {}
        if workspace_id:
            match["workspace_id"] = ObjectId(workspace_id)
        if user_id:
            match["user_id"] = ObjectId(user_id)
            
        if start_date or end_date:
            match["timestamp"] = {}
            if start_date:
                match["timestamp"]["$gte"] = start_date
            if end_date:
                match["timestamp"]["$lte"] = end_date
                
        pipeline = [
            {"$match": match},
            {"$group": {
                "_id": None,
                "total_compute_seconds": {"$sum": "$compute_seconds"},
                "total_storage_bytes": {"$sum": "$storage_bytes"},
                "pipelines_executed": {"$sum": {"$cond": [{"$eq": ["$type", "pipeline_execution"]}, 1, 0]}},
                "reports_generated": {"$sum": {"$cond": [{"$eq": ["$type", "report_generation"]}, 1, 0]}}
            }}
        ]
        
        cursor = self.collection.aggregate(pipeline)
        results = await cursor.to_list(length=1)
        if results:
            data = results[0]
            data.pop("_id", None)
            return data
        return {
            "total_compute_seconds": 0,
            "total_storage_bytes": 0,
            "pipelines_executed": 0,
            "reports_generated": 0
        }

usage_repository = UsageRepository()
