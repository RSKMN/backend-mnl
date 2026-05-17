from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class TargetCreate(BaseModel):
    gene: Optional[str] = Field(default=None, description="Target gene name, e.g. EGFR")
    uniprot_id: Optional[str] = Field(default=None, description="UniProt primary accession ID, e.g. P00533")
    protein_name: Optional[str] = Field(default=None, description="Full protein name description")
    structure_file_id: Optional[str] = Field(default=None, description="Optional uploaded protein structure file UUID")
    rank_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Rank prioritization score between 0 and 1")
    status: Optional[str] = Field(default="candidate", description="Allowed: candidate, selected, rejected, archived")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom experimental metadata dictionary")

class TargetResponse(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    gene: Optional[str] = None
    uniprot_id: Optional[str] = None
    protein_name: Optional[str] = None
    structure_file_id: Optional[str] = None
    rank_score: Optional[float] = None
    status: str
    metadata: Dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mongo(cls, doc: dict):
        if not doc:
            return None
        data = dict(doc)
        data["id"] = str(data["_id"])
        
        # Serialize fields that are ObjectIds to string
        for field in ["project_id", "workspace_id", "created_by"]:
            if field in data and data[field]:
                data[field] = str(data[field])
                
        return cls(**data)

class TargetRankRequest(BaseModel):
    target_ids: Optional[List[str]] = None
    strategy: Optional[str] = "manual"
