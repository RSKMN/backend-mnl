import re
from bson import ObjectId
from app.repositories.workspace_repository import workspace_repository
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

def generate_slug(name: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', name).strip('-').lower()
    return slug

class WorkspaceService:
    async def create_workspace(self, name: str, user_id: str) -> dict:
        now = utc_now()
        slug = generate_slug(name)
        existing_workspace = await workspace_repository.get_workspace_by_slug(slug)
        if existing_workspace:
            slug = f"{slug}-{str(user_id)[:6]}"

        workspace_doc = {
            "name": name,
            "slug": slug,
            "owner_user_id": ObjectId(user_id),
            "plan": "development",
            "created_at": now,
            "updated_at": now
        }
        workspace = await workspace_repository.create_workspace(workspace_doc)

        member_doc = {
            "workspace_id": workspace["_id"],
            "user_id": ObjectId(user_id),
            "role": "owner",
            "status": "active",
            "created_at": now
        }
        await workspace_repository.create_member(member_doc)
        
        workspace["role"] = "owner"
        return workspace

    async def get_user_workspaces(self, user_id: str):
        return await workspace_repository.get_user_workspaces(user_id)

    async def get_workspace(self, workspace_id: str, user_id: str):
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(status_code=403, code="WORKSPACE_ACCESS_DENIED", message="User is not an active member of this workspace")
        
        workspace = await workspace_repository.get_workspace_by_id(workspace_id)
        if not workspace:
            raise AppException(status_code=404, code="WORKSPACE_NOT_FOUND", message="Workspace not found")
            
        workspace["role"] = membership["role"]
        return workspace

workspace_service = WorkspaceService()
