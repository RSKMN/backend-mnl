import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Dict, Any

class ProjectRepository:
    @property
    def collection(self):
        return get_database()["projects"]

    async def ensure_indexes(self):
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("created_by")
        await self.collection.create_index("status")
        await self.collection.create_index(
            [("workspace_id", pymongo.ASCENDING), ("slug", pymongo.ASCENDING)],
            unique=True
        )

    async def create_project(self, project_doc: dict) -> dict:
        result = await self.collection.insert_one(project_doc)
        return await self.get_project_by_id(str(result.inserted_id))

    async def get_project_by_id(self, project_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(project_id):
            return None
        return await self.collection.find_one({"_id": ObjectId(project_id)})

    async def list_projects(self, workspace_id: str, status: Optional[str] = None, search: Optional[str] = None, skip: int = 0, limit: int = 20) -> tuple[List[dict], int]:
        query = {"workspace_id": ObjectId(workspace_id)}
        
        if status:
            query["status"] = status
        else:
            query["status"] = {"$ne": "archived"}
            
        if search:
            query["name"] = {"$regex": search, "$options": "i"}

        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort("created_at", pymongo.DESCENDING).skip(skip).limit(limit)
        projects = await cursor.to_list(length=limit)
        
        return projects, total

    async def update_project(self, project_id: str, update_data: dict) -> Optional[dict]:
        if not ObjectId.is_valid(project_id):
            return None
        await self.collection.update_one(
            {"_id": ObjectId(project_id)},
            {"$set": update_data}
        )
        return await self.get_project_by_id(project_id)

    async def archive_project(self, project_id: str, updated_at: Any) -> bool:
        if not ObjectId.is_valid(project_id):
            return False
        result = await self.collection.update_one(
            {"_id": ObjectId(project_id)},
            {"$set": {"status": "archived", "updated_at": updated_at}}
        )
        return result.modified_count > 0

    async def slug_exists(self, workspace_id: str, slug: str) -> bool:
        doc = await self.collection.find_one({
            "workspace_id": ObjectId(workspace_id),
            "slug": slug
        })
        return doc is not None

    async def generate_unique_slug(self, workspace_id: str, name: str) -> str:
        from app.utils.slug import generate_slug
        base_slug = generate_slug(name)
        slug = base_slug
        counter = 2
        while await self.slug_exists(workspace_id, slug):
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

project_repository = ProjectRepository()

