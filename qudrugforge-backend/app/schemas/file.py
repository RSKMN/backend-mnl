from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class FileMetadataResponse(BaseModel):
    file_id: str
    project_id: str
    workspace_id: str
    uploaded_by: str
    original_filename: str
    stored_filename: str
    file_type: str
    mime_type: str
    local_path: str
    size_bytes: int
    checksum: str
    source_module: str
    kind: str = "uploaded"
    artifact_type: str
    linked_experiment_id: Optional[str] = None
    storage_provider: str = "local"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mongo(cls, doc: dict):
        """
        Converts MongoDB document to FileMetadataResponse schema with deserialized ObjectIds.
        """
        if not doc:
            return None
        data = dict(doc)
        
        # Serialize fields that are ObjectIds to string
        for field in ["project_id", "workspace_id", "uploaded_by"]:
            if field in data and data[field]:
                data[field] = str(data[field])
                
        if "linked_experiment_id" in data and data["linked_experiment_id"]:
            data["linked_experiment_id"] = str(data["linked_experiment_id"])
            
        return cls(**data)

class FileListResponse(BaseModel):
    items: List[FileMetadataResponse]
    total: int
    limit: int
    offset: int
