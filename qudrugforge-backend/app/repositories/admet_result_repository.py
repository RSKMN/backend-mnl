import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple

class AdmetResultRepository:
    @property
    def collection(self):
        return get_database()["admet_results"]

    async def ensure_indexes(self):
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("experiment_id")
        await self.collection.create_index("import_id")
        await self.collection.create_index("compound_id")
        await self.collection.create_index("smiles")
        await self.collection.create_index("status")
        await self.collection.create_index("created_at")

    async def create_many(self, docs: List[dict]) -> int:
        if not docs:
            return 0
        result = await self.collection.insert_many(docs)
        return len(result.inserted_ids)

    async def list_results(
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
        cursor = self.collection.find(query).sort("created_at", pymongo.ASCENDING).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total

admet_result_repository = AdmetResultRepository()
