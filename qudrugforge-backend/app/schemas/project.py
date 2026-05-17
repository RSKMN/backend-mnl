from pydantic import BaseModel, Field, constr
from typing import Optional
from datetime import datetime

class ProjectCreate(BaseModel):
    workspace_id: str
    name: constr(min_length=2, max_length=150)
    description: Optional[constr(max_length=2000)] = None
    disease_type: Optional[constr(max_length=150)] = None
    cancer_type: Optional[constr(max_length=150)] = None

class ProjectUpdate(BaseModel):
    name: Optional[constr(min_length=2, max_length=150)] = None
    description: Optional[constr(max_length=2000)] = None
    disease_type: Optional[constr(max_length=150)] = None
    cancer_type: Optional[constr(max_length=150)] = None
    status: Optional[str] = None

class ProjectResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    slug: str
    description: Optional[str] = None
    disease_type: Optional[str] = None
    cancer_type: Optional[str] = None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mongo(cls, doc: dict):
        return cls(
            id=str(doc["_id"]),
            workspace_id=str(doc["workspace_id"]),
            name=doc["name"],
            slug=doc["slug"],
            description=doc.get("description"),
            disease_type=doc.get("disease_type"),
            cancer_type=doc.get("cancer_type"),
            status=doc["status"],
            created_by=str(doc["created_by"]),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"]
        )
