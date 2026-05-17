import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List, Tuple

class FileMetadataRepository:
    @property
    def collection(self):
        return get_database()["files"]

    async def ensure_indexes(self):
        await self.collection.create_index("file_id", unique=True)
        await self.collection.create_index("project_id")
        await self.collection.create_index("workspace_id")
        await self.collection.create_index("uploaded_by")
        await self.collection.create_index("file_type")
        await self.collection.create_index("source_module")
        await self.collection.create_index("created_at")

    async def create_metadata(self, file_doc: dict) -> dict:
        result = await self.collection.insert_one(file_doc)
        return await self.collection.find_one({"_id": result.inserted_id})

    async def get_metadata_by_file_id(self, file_id: str) -> Optional[dict]:
        return await self.collection.find_one({"file_id": file_id})

    async def get_by_file_id(self, file_id: str) -> Optional[dict]:
        """
        Alias method to retrieve file metadata by public UUID string.
        """
        return await self.collection.find_one({"file_id": file_id})


    async def list_metadata_by_project(
        self,
        project_id: str,
        file_type: Optional[str] = None,
        source_module: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[dict], int]:
        query = {"project_id": ObjectId(project_id)}
        
        if file_type:
            query["file_type"] = file_type
        if source_module:
            query["source_module"] = source_module

        total = await self.collection.count_documents(query)
        cursor = self.collection.find(query).sort("created_at", pymongo.DESCENDING).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        
        return items, total

    async def delete_metadata_by_file_id(self, file_id: str) -> bool:
        result = await self.collection.delete_one({"file_id": file_id})
        return result.deleted_count > 0

file_metadata_repository = FileMetadataRepository()
