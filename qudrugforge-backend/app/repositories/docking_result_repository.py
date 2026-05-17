import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple


class DockingResultRepository:
    @property
    def collection(self):
        return get_database()["docking_results"]

    async def ensure_indexes(self):
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("experiment_id")
        await self.collection.create_index("import_id")
        await self.collection.create_index("compound_id")
        await self.collection.create_index("molecule_id")
        await self.collection.create_index("target_id")
        await self.collection.create_index("smiles")
        await self.collection.create_index("status")
        await self.collection.create_index("source")
        await self.collection.create_index("created_at")
        # Compound indexes for common query patterns
        await self.collection.create_index(
            [("project_id", pymongo.ASCENDING), ("experiment_id", pymongo.ASCENDING)]
        )
        await self.collection.create_index(
            [("project_id", pymongo.ASCENDING), ("rank", pymongo.ASCENDING)]
        )

    async def create_many(self, docs: List[dict]) -> int:
        if not docs:
            return 0
        result = await self.collection.insert_many(docs)
        return len(result.inserted_ids)

    async def list_results(
        self,
        project_id: str,
        experiment_id: Optional[str] = None,
        molecule_id: Optional[str] = None,
        target_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
        sort_by: str = "rank",
        sort_order: int = pymongo.ASCENDING
    ) -> Tuple[List[dict], int]:
        query: dict = {"project_id": ObjectId(project_id)}

        if experiment_id:
            # experiment_id stored as ObjectId in imported docs
            try:
                query["experiment_id"] = ObjectId(experiment_id)
            except Exception:
                query["experiment_id"] = experiment_id

        if molecule_id:
            try:
                query["molecule_id"] = ObjectId(molecule_id)
            except Exception:
                query["molecule_id"] = molecule_id

        if target_id:
            try:
                query["target_id"] = ObjectId(target_id)
            except Exception:
                query["target_id"] = target_id

        total = await self.collection.count_documents(query)
        cursor = (
            self.collection.find(query)
            .sort(sort_by, sort_order)
            .skip(skip)
            .limit(limit)
        )
        items = await cursor.to_list(length=limit)
        return items, total

    async def get_result_by_id(self, result_id: str) -> Optional[dict]:
        try:
            return await self.collection.find_one({"_id": ObjectId(result_id)})
        except Exception:
            return None


docking_result_repository = DockingResultRepository()
