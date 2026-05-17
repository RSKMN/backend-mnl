from pydantic import BaseModel, Field
from datetime import datetime
from app.utils.object_id import PyObjectId

class WorkspaceBase(BaseModel):
    name: str

class WorkspaceCreate(WorkspaceBase):
    pass

class WorkspaceInDB(WorkspaceBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    slug: str
    owner_user_id: PyObjectId
    plan: str = "development"
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

class WorkspaceResponse(WorkspaceBase):
    id: str
    slug: str
    role: str = "member"

    @classmethod
    def from_mongo(cls, workspace_data: dict, role: str):
        return cls(
            id=str(workspace_data["_id"]),
            name=workspace_data["name"],
            slug=workspace_data["slug"],
            role=role
        )
