import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple

class ReportRepository:
    @property
    def collection(self):
        return get_database()["reports"]

    async def ensure_indexes(self):
        await self.collection.create_index("report_id", unique=True)
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("experiment_id")
        await self.collection.create_index("import_id")
        await self.collection.create_index("created_at")

    async def create_report(self, report_doc: dict) -> dict:
        result = await self.collection.insert_one(report_doc)
        return await self.collection.find_one({"_id": result.inserted_id})

    async def get_by_report_id(self, report_id: str) -> Optional[dict]:
        return await self.collection.find_one({"report_id": report_id})

    async def list_reports(
        self,
        project_id: str,
        experiment_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Tuple[List[dict], int]:
        query = {"project_id": ObjectId(project_id)}
        if experiment_id:
            query["experiment_id"] = experiment_id

        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort("created_at", pymongo.DESCENDING).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total

report_repository = ReportRepository()
