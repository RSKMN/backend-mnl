import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple
from datetime import datetime
from app.utils.datetime import utc_now

class PipelineRepository:
    @property
    def collection(self):
        return get_database()["pipeline_runs"]

    async def ensure_indexes(self):
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("status")
        await self.collection.create_index("created_at")

    async def create_pipeline_run(self, doc: dict) -> dict:
        result = await self.collection.insert_one(doc)
        return await self.collection.find_one({"_id": result.inserted_id})

    async def get_pipeline_run_by_id(self, pipeline_run_id: str) -> Optional[dict]:
        try:
            return await self.collection.find_one({"_id": ObjectId(pipeline_run_id)})
        except Exception:
            return None

    async def get_pipeline_run_by_id_and_project(self, pipeline_run_id: str, project_id: str) -> Optional[dict]:
        try:
            return await self.collection.find_one({
                "_id": ObjectId(pipeline_run_id),
                "project_id": ObjectId(project_id)
            })
        except Exception:
            return None

    async def list_pipeline_runs(
        self,
        project_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[dict], int]:
        query = {"project_id": ObjectId(project_id)}
        if status:
            query["status"] = status

        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort("created_at", pymongo.DESCENDING).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total

    async def update_pipeline_status(self, pipeline_run_id: str, status: str) -> Optional[dict]:
        await self.collection.update_one(
            {"_id": ObjectId(pipeline_run_id)},
            {
                "$set": {
                    "status": status,
                    "updated_at": utc_now()
                }
            }
        )
        return await self.get_pipeline_run_by_id(pipeline_run_id)

    async def update_stage_status(
        self,
        pipeline_run_id: str,
        stage: str,
        stage_status_doc: dict
    ) -> Optional[dict]:
        # Form dynamic path update key: stage_statuses.stage_name
        update_key = f"stage_statuses.{stage}"
        await self.collection.update_one(
            {"_id": ObjectId(pipeline_run_id)},
            {
                "$set": {
                    update_key: stage_status_doc,
                    "updated_at": utc_now()
                }
            }
        )
        return await self.get_pipeline_run_by_id(pipeline_run_id)

pipeline_repository = PipelineRepository()
