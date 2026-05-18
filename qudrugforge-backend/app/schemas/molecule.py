from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class MoleculeResponse(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    source_file_id: Optional[str] = None
    compound_id: str
    name: Optional[str] = None
    smiles: str
    inchi: Optional[str] = None
    inchikey: Optional[str] = None
    mw: Optional[float] = None
    logp: Optional[float] = None
    qed: Optional[float] = None
    tpsa: Optional[float] = None
    status: str
    source: str
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
                
        if "created_by" not in data or not data["created_by"]:
            data["created_by"] = "system"
                
        return cls(**data)

class MoleculeImportRequest(BaseModel):
    source_file_id: str
    smiles_column: Optional[str] = None
    compound_id_column: Optional[str] = None
    name_column: Optional[str] = None

class MoleculeImportSummary(BaseModel):
    source_file_id: str
    created_count: int
    skipped_count: int
    duplicate_count: int
    invalid_count: int
    items: List[MoleculeResponse]

class MoleculeFilterRequest(BaseModel):
    mw_min: Optional[float] = None
    mw_max: Optional[float] = None
    logp_min: Optional[float] = None
    logp_max: Optional[float] = None
    qed_min: Optional[float] = None
    tpsa_max: Optional[float] = None
    mark_filtered: Optional[bool] = False

class MoleculeGenerateRequest(BaseModel):
    count: int = Field(default=10, ge=1)
    strategy: str = "mock"
