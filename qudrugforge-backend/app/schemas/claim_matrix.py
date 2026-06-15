from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class ClaimMatrixEntry(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    experiment_id: Optional[str] = None
    import_id: Optional[str] = None
    evidence_level: Optional[str] = None
    name: Optional[str] = None
    definition: Optional[str] = None
    current_status: Optional[str] = None
    allowed_claim: Optional[str] = None
    forbidden_claim: Optional[str] = None
    required_next_evidence: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_mongo(cls, doc: dict) -> "ClaimMatrixEntry":
        data = dict(doc)
        data["id"] = str(data.pop("_id"))
        for field in ("project_id", "workspace_id", "experiment_id"):
            if field in data and data[field] is not None:
                data[field] = str(data[field])
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

class ClaimMatrixListResponse(BaseModel):
    items: List[ClaimMatrixEntry]
    total: int

class ClaimMatrixSummary(BaseModel):
    total_claims: int
    levels_count: Dict[str, int]
    status_counts: Dict[str, int]
