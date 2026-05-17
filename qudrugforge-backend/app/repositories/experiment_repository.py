import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple
from datetime import datetime
from app.utils.datetime import utc_now

class ExperimentRepository:
    @property
    def collection(self):
        return get_database()["experiments"]

    async def ensure_indexes(self):
        """
        Creates all required core and compound indexes for fast searching and scoping.
        """
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("status")
        await self.collection.create_index("type")
        await self.collection.create_index("engine")
        await self.collection.create_index("created_at")
        await self.collection.create_index("q_ai_drug_job_id")
        
        # Compound indexes
        await self.collection.create_index([("project_id", pymongo.ASCENDING), ("status", pymongo.ASCENDING)])
        await self.collection.create_index([("project_id", pymongo.ASCENDING), ("type", pymongo.ASCENDING)])
        await self.collection.create_index([("project_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)])

    async def create_experiment(self, doc: dict) -> dict:
        result = await self.collection.insert_one(doc)
        return await self.collection.find_one({"_id": result.inserted_id})

    async def list_experiments(
        self,
        project_id: str,
        status: Optional[str] = None,
        type: Optional[str] = None,
        engine: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[dict], int]:
        query = {"project_id": ObjectId(project_id)}
        if status:
            query["status"] = status
        if type:
            query["type"] = type
        if engine:
            query["engine"] = engine

        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort("created_at", pymongo.DESCENDING).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total

    async def get_experiment_by_id(self, experiment_id: str) -> Optional[dict]:
        try:
            return await self.collection.find_one({"_id": ObjectId(experiment_id)})
        except Exception:
            return None

    async def get_experiment_by_id_and_project(self, experiment_id: str, project_id: str) -> Optional[dict]:
        try:
            return await self.collection.find_one({
                "_id": ObjectId(experiment_id),
                "project_id": ObjectId(project_id)
            })
        except Exception:
            return None

    async def update_experiment(self, experiment_id: str, update_doc: dict) -> Optional[dict]:
        await self.collection.update_one(
            {"_id": ObjectId(experiment_id)},
            {"$set": update_doc}
        )
        return await self.get_experiment_by_id(experiment_id)

    async def update_status_progress(
        self,
        experiment_id: str,
        status: str,
        progress: int,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error: Optional[str] = None
    ) -> Optional[dict]:
        set_dict = {
            "status": status,
            "progress": progress,
            "updated_at": utc_now()
        }
        if started_at:
            set_dict["started_at"] = started_at
        if completed_at:
            set_dict["completed_at"] = completed_at
        if error is not None:
            set_dict["error"] = error
            
        await self.collection.update_one(
            {"_id": ObjectId(experiment_id)},
            {"$set": set_dict}
        )
        return await self.get_experiment_by_id(experiment_id)

    async def append_log(self, experiment_id: str, log_item: dict) -> Optional[dict]:
        await self.collection.update_one(
            {"_id": ObjectId(experiment_id)},
            {
                "$push": {"logs": log_item},
                "$set": {"updated_at": utc_now()}
            }
        )
        return await self.get_experiment_by_id(experiment_id)

    async def append_output_file_ids(self, experiment_id: str, file_ids: List[str]) -> Optional[dict]:
        await self.collection.update_one(
            {"_id": ObjectId(experiment_id)},
            {
                "$addToSet": {"output_file_ids": {"$each": file_ids}},
                "$set": {"updated_at": utc_now()}
            }
        )
        return await self.get_experiment_by_id(experiment_id)

    async def get_logs(self, experiment_id: str) -> List[dict]:
        exp = await self.get_experiment_by_id(experiment_id)
        if not exp:
            return []
        return exp.get("logs", [])

    async def summary_by_project(self, project_id: str) -> dict:
        pipeline = [
            {"$match": {"project_id": ObjectId(project_id)}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]
        
        counts = {
            "total": 0,
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "imported": 0,
            "active": 0
        }
        
        cursor = self.collection.aggregate(pipeline)
        async for doc in cursor:
            status = doc["_id"]
            count = doc["count"]
            counts["total"] += count
            if status in counts:
                counts[status] = count
                
        # active count = queued + running
        counts["active"] = counts["queued"] + counts["running"]
        
        return counts

experiment_repository = ExperimentRepository()
