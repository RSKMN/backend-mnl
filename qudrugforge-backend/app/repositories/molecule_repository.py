import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple, Set

class MoleculeRepository:
    @property
    def collection(self):
        return get_database()["molecules"]

    async def ensure_indexes(self):
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("source_file_id")
        await self.collection.create_index("compound_id")
        await self.collection.create_index("smiles")
        await self.collection.create_index("status")
        await self.collection.create_index("created_at")
        
        # Compound unique index project_id + compound_id
        await self.collection.create_index(
            [("project_id", pymongo.ASCENDING), ("compound_id", pymongo.ASCENDING)],
            unique=True
        )
        
        # Non-unique project_id + smiles index
        await self.collection.create_index(
            [("project_id", pymongo.ASCENDING), ("smiles", pymongo.ASCENDING)]
        )

    async def create_many_molecules(self, molecule_docs: List[dict]) -> int:
        if not molecule_docs:
            return 0
        result = await self.collection.insert_many(molecule_docs)
        return len(result.inserted_ids)

    async def list_molecules(
        self,
        project_id: str,
        status: Optional[str] = None,
        search: Optional[str] = None,
        source_file_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Tuple[List[dict], int]:
        query = {"project_id": ObjectId(project_id)}
        
        if status:
            query["status"] = status
        if source_file_id:
            query["source_file_id"] = source_file_id
            
        if search:
            query["$or"] = [
                {"compound_id": {"$regex": search, "$options": "i"}},
                {"name": {"$regex": search, "$options": "i"}},
                {"smiles": {"$regex": search, "$options": "i"}}
            ]
            
        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort("created_at", pymongo.ASCENDING).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        
        return items, total

    async def get_molecule_by_id(self, molecule_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(molecule_id):
            return None
        return await self.collection.find_one({"_id": ObjectId(molecule_id)})

    async def smiles_exists_in_project(self, project_id: str, smiles: str) -> bool:
        doc = await self.collection.find_one({"project_id": ObjectId(project_id), "smiles": smiles})
        return doc is not None

    async def get_existing_smiles_set(self, project_id: str, smiles_list: List[str]) -> Set[str]:
        if not smiles_list:
            return set()
        cursor = self.collection.find(
            {"project_id": ObjectId(project_id), "smiles": {"$in": smiles_list}},
            {"smiles": 1}
        )
        items = await cursor.to_list(length=len(smiles_list))
        return {item["smiles"] for item in items}

    async def get_max_compound_id_suffix(self, project_id: str) -> int:
        cursor = self.collection.find(
            {"project_id": ObjectId(project_id), "compound_id": {"$regex": "^QDF-"}}
        ).sort("compound_id", pymongo.DESCENDING).limit(1)
        items = await cursor.to_list(length=1)
        if not items:
            return 0
        
        cid = items[0]["compound_id"]
        try:
            parts = cid.split("-")
            if len(parts) > 1:
                return int(parts[1])
        except Exception:
            pass
        return 0

    async def filter_molecules(self, project_id: str, criteria: dict, mark_filtered: bool, updated_at: any) -> List[dict]:
        query = {"project_id": ObjectId(project_id)}
        
        # Build range queries
        for field in ["mw", "logp", "qed"]:
            field_min = criteria.get(f"{field}_min")
            field_max = criteria.get(f"{field}_max")
            
            field_query = {}
            if field_min is not None:
                field_query["$gte"] = float(field_min)
            if field_max is not None:
                field_query["$lte"] = float(field_max)
                
            if field_query:
                # Exclude null values when filters are actively applied
                field_query["$ne"] = None
                query[field] = field_query
                
        tpsa_max = criteria.get("tpsa_max")
        if tpsa_max is not None:
            query["tpsa"] = {"$lte": float(tpsa_max), "$ne": None}
            
        cursor = self.collection.find(query).sort("created_at", pymongo.ASCENDING)
        items = await cursor.to_list(length=None)
        
        if mark_filtered and items:
            item_ids = [item["_id"] for item in items]
            await self.collection.update_many(
                {"_id": {"$in": item_ids}},
                {"$set": {"status": "filtered", "updated_at": updated_at}}
            )
            # Re-fetch with updated status
            cursor = self.collection.find({"_id": {"$in": item_ids}}).sort("created_at", pymongo.ASCENDING)
            items = await cursor.to_list(length=None)
            
        return items

    async def count_by_project(self, project_id: str) -> int:
        if not ObjectId.is_valid(project_id):
            return 0
        return await self.collection.count_documents({"project_id": ObjectId(project_id)})

molecule_repository = MoleculeRepository()
