import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple, Dict

class ClaimMatrixRepository:
    @property
    def collection(self):
        return get_database()["claim_matrix"]

    async def ensure_indexes(self):
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("experiment_id")
        await self.collection.create_index("import_id")
        await self.collection.create_index("evidence_level")
        await self.collection.create_index("current_status")
        await self.collection.create_index([("project_id", pymongo.ASCENDING), ("evidence_level", pymongo.ASCENDING)])

    async def create_many(self, docs: List[dict]) -> int:
        if not docs:
            return 0
        result = await self.collection.insert_many(docs)
        return len(result.inserted_ids)

    async def get_by_project(self, project_id: str) -> Tuple[List[dict], int]:
        query = {"project_id": ObjectId(project_id)}
        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort([("evidence_level", pymongo.ASCENDING)])
        items = await cursor.to_list(length=None)
        return items, total

    async def get_summary(self, project_id: str) -> Dict:
        query = {"project_id": ObjectId(project_id)}
        cursor = self.collection.find(query)
        items = await cursor.to_list(length=None)

        total_claims = len(items)
        levels_count = {}
        status_counts = {}

        for item in items:
            lvl = item.get("evidence_level")
            if lvl:
                levels_count[lvl] = levels_count.get(lvl, 0) + 1
            
            status = item.get("current_status")
            if status:
                status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "total_claims": total_claims,
            "levels_count": levels_count,
            "status_counts": status_counts
        }

claim_matrix_repository = ClaimMatrixRepository()
