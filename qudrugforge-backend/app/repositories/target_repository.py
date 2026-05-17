import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple
from pymongo import UpdateOne

class TargetRepository:
    @property
    def collection(self):
        return get_database()["targets"]

    async def ensure_indexes(self):
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("gene")
        await self.collection.create_index("uniprot_id")
        await self.collection.create_index("status")
        await self.collection.create_index("rank_score")
        await self.collection.create_index([("project_id", pymongo.ASCENDING), ("gene", pymongo.ASCENDING)])
        await self.collection.create_index([("project_id", pymongo.ASCENDING), ("uniprot_id", pymongo.ASCENDING)])

    async def create_target(self, target_doc: dict) -> dict:
        result = await self.collection.insert_one(target_doc)
        return await self.collection.find_one({"_id": result.inserted_id})

    async def list_targets(
        self,
        project_id: str,
        status: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[dict], int]:
        query = {"project_id": ObjectId(project_id)}
        
        if status:
            query["status"] = status
            
        if search:
            query["$or"] = [
                {"gene": {"$regex": search, "$options": "i"}},
                {"uniprot_id": {"$regex": search, "$options": "i"}},
                {"protein_name": {"$regex": search, "$options": "i"}}
            ]
            
        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort("rank_score", pymongo.DESCENDING).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        
        return items, total

    async def get_target_by_id(self, target_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(target_id):
            return None
        return await self.collection.find_one({"_id": ObjectId(target_id)})

    async def update_target_rank_scores(self, updates: List[Tuple[str, float]], updated_at: any) -> bool:
        """
        Executes a bulk update for multiple target rank scores in a single DB trip.
        """
        if not updates:
            return False
            
        operations = []
        for target_id, score in updates:
            if ObjectId.is_valid(target_id):
                operations.append(
                    UpdateOne(
                        {"_id": ObjectId(target_id)},
                        {"$set": {"rank_score": score, "updated_at": updated_at}}
                    )
                )
                
        if operations:
            await self.collection.bulk_write(operations)
            return True
        return False

    async def count_by_project(self, project_id: str) -> int:
        if not ObjectId.is_valid(project_id):
            return 0
        return await self.collection.count_documents({"project_id": ObjectId(project_id)})

target_repository = TargetRepository()
