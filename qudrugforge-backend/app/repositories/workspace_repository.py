from bson import ObjectId
from app.core.database import get_database
from typing import Optional, List

class WorkspaceRepository:
    @property
    def workspaces_collection(self):
        return get_database()["workspaces"]
        
    @property
    def members_collection(self):
        return get_database()["workspace_members"]

    async def get_workspace_by_id(self, workspace_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(workspace_id):
            return None
        return await self.workspaces_collection.find_one({"_id": ObjectId(workspace_id)})

    async def get_workspace_by_slug(self, slug: str) -> Optional[dict]:
        return await self.workspaces_collection.find_one({"slug": slug})

    async def create_workspace(self, workspace_doc: dict) -> dict:
        result = await self.workspaces_collection.insert_one(workspace_doc)
        return await self.get_workspace_by_id(str(result.inserted_id))

    async def create_member(self, member_doc: dict) -> dict:
        result = await self.members_collection.insert_one(member_doc)
        return await self.members_collection.find_one({"_id": result.inserted_id})

    async def get_user_workspaces(self, user_id: str) -> List[dict]:
        if not ObjectId.is_valid(user_id):
            return []
        
        # Find all memberships for the user
        memberships = await self.members_collection.find({"user_id": ObjectId(user_id), "status": "active"}).to_list(length=None)
        
        if not memberships:
            return []
            
        workspace_ids = [m["workspace_id"] for m in memberships]
        
        # Find workspaces corresponding to those IDs
        workspaces = await self.workspaces_collection.find({"_id": {"$in": workspace_ids}}).to_list(length=None)
        
        # Combine role info
        result = []
        for ws in workspaces:
            membership = next((m for m in memberships if m["workspace_id"] == ws["_id"]), None)
            if membership:
                ws["role"] = membership["role"]
                result.append(ws)
                
        return result

    async def get_membership(self, workspace_id: str, user_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(workspace_id) or not ObjectId.is_valid(user_id):
            return None
            
        return await self.members_collection.find_one({
            "workspace_id": ObjectId(workspace_id),
            "user_id": ObjectId(user_id),
            "status": "active"
        })

workspace_repository = WorkspaceRepository()
