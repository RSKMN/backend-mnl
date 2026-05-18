import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple

class QuantumResultRepository:
    @property
    def collection(self):
        return get_database()["quantum_results"]

    async def ensure_indexes(self):
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("experiment_id")
        await self.collection.create_index("import_id")
        await self.collection.create_index("molecule_id")
        await self.collection.create_index("compound_id")
        await self.collection.create_index("smiles")
        await self.collection.create_index("quantum_prefilter_score")
        await self.collection.create_index("quantum_kernel_score")
        await self.collection.create_index("qml_score")
        await self.collection.create_index("quantum_rank")
        await self.collection.create_index("rank")
        await self.collection.create_index("status")
        await self.collection.create_index("created_at")
        await self.collection.create_index(
            [("project_id", pymongo.ASCENDING), ("experiment_id", pymongo.ASCENDING)]
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
        result_kind: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "created_at",
        sort_order: int = pymongo.ASCENDING,
    ) -> Tuple[List[dict], int]:
        query = {"project_id": ObjectId(project_id)}
        if experiment_id:
            try:
                query["experiment_id"] = ObjectId(experiment_id)
            except Exception:
                query["experiment_id"] = experiment_id

        if result_kind == "descriptors":
            query["qm_descriptors"] = {"$ne": {}}
        elif result_kind == "qml_scores":
            query["$or"] = [
                {"quantum_prefilter_score": {"$ne": None}},
                {"quantum_kernel_score": {"$ne": None}},
                {"qml_score": {"$ne": None}},
            ]
        elif result_kind == "prefilter":
            query["quantum_prefilter_score"] = {"$ne": None}
        elif result_kind == "reranking":
            query["$or"] = [
                {"quantum_kernel_score": {"$ne": None}},
                {"qml_score": {"$ne": None}},
            ]

        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort(sort_by, sort_order).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total

quantum_result_repository = QuantumResultRepository()
