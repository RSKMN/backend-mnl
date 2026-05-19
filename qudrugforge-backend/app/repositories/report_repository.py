"""
Phase 16A — Report Repository
MongoDB/Motor data access layer for the `reports` collection.
Handles CRUD + index management. No file generation.
"""
import pymongo
from bson import ObjectId
from typing import Optional, List, Tuple, Dict, Any
from app.core.database import get_database


class ReportRepository:

    @property
    def collection(self):
        return get_database()["reports"]

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------

    async def ensure_indexes(self) -> None:
        await self.collection.create_index("report_id", unique=True)
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("experiment_id")
        await self.collection.create_index("status")
        await self.collection.create_index("report_type")
        await self.collection.create_index("source")
        await self.collection.create_index("created_at")
        await self.collection.create_index("import_id")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create_report(self, report_doc: dict) -> dict:
        result = await self.collection.insert_one(report_doc)
        return await self.collection.find_one({"_id": result.inserted_id})

    async def update_report(self, report_id: str, update_data: dict) -> Optional[dict]:
        await self.collection.update_one(
            {"report_id": report_id},
            {"$set": update_data}
        )
        return await self.get_by_report_id(report_id)

    async def delete_report(self, report_id: str) -> bool:
        result = await self.collection.delete_one({"report_id": report_id})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # Read — single
    # ------------------------------------------------------------------

    async def get_by_report_id(self, report_id: str) -> Optional[dict]:
        return await self.collection.find_one({"report_id": report_id})

    async def get_by_import_id_and_project(
        self, import_id: str, project_id: str
    ) -> Optional[dict]:
        return await self.collection.find_one(
            {"import_id": import_id, "project_id": ObjectId(project_id)}
        )

    async def find_duplicate_import(
        self, project_id: str, source_output_dir: str
    ) -> Optional[dict]:
        """Detect an already-imported q-ai-drug report for the same source dir."""
        return await self.collection.find_one(
            {
                "project_id": ObjectId(project_id),
                "source": "q_ai_drug",
                "metadata.imported_source_dir": source_output_dir,
            }
        )

    # ------------------------------------------------------------------
    # Read — list
    # ------------------------------------------------------------------

    async def list_reports(
        self,
        project_id: str,
        report_type: Optional[str] = None,
        status: Optional[str] = None,
        experiment_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[dict], int]:
        query: Dict[str, Any] = {"project_id": ObjectId(project_id)}

        if report_type:
            query["report_type"] = report_type
        if status:
            query["status"] = status
        if experiment_id:
            try:
                query["experiment_id"] = ObjectId(experiment_id)
            except Exception:
                query["experiment_id"] = experiment_id

        total = await self.collection.count_documents(query)
        cursor = (
            self.collection.find(query)
            .sort("created_at", pymongo.DESCENDING)
            .skip(skip)
            .limit(limit)
        )
        items = await cursor.to_list(length=limit)
        return items, total

    # ------------------------------------------------------------------
    # Aggregated counts (used by summary route)
    # ------------------------------------------------------------------

    async def count_by_status(self, project_id: str) -> Dict[str, int]:
        pipeline = [
            {"$match": {"project_id": ObjectId(project_id)}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        result = {}
        async for doc in self.collection.aggregate(pipeline):
            result[doc["_id"]] = doc["count"]
        return result

    async def count_total(self, project_id: str) -> int:
        return await self.collection.count_documents(
            {"project_id": ObjectId(project_id)}
        )


report_repository = ReportRepository()
