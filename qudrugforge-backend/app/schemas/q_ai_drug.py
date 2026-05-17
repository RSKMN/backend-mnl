from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class QAiDrugHealthResponse(BaseModel):
    available: bool = Field(..., description="Flags if the q-ai-drug backend cluster is online")
    base_url: str = Field(..., description="Underlying cluster connection URL")
    health: Optional[Dict[str, Any]] = Field(default=None, description="Actual raw health status return payload")
    error: Optional[str] = Field(default=None, description="Clear connection error details if down")

class QAiDrugNormalizedResponse(BaseModel):
    project_id: str = Field(..., description="Target project ID associated with this search query")
    source: str = Field(default="q-ai-drug", description="Static scientific data source label")
    items: List[Any] = Field(default_factory=list, description="Unified normalized list arrays")
    raw: Dict[str, Any] = Field(default_factory=dict, description="Raw dictionary return payload for dev/debug tracking")
    last_synced_at: str = Field(..., description="UTC timestamp of the execution transaction")
