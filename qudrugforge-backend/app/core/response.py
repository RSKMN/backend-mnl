from typing import Generic, TypeVar, Optional, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime

T = TypeVar("T")

class ProvenanceMetadata(BaseModel):
    source: str = Field(..., description="Origin of the data: backend-mnl, q-ai-drug, imported, or simulated")
    evidence_status: str = Field(..., description="Validity of the data: verified, unverified, missing, placeholder")
    import_batch_id: Optional[str] = None
    engine: Optional[str] = None
    claim_boundary: Optional[str] = None
    provenance_notes: Optional[str] = None
    
    # TODO: Prepare for Phase C artifact invalidation
    # stale: bool = False
    # outdated: bool = False
    # archived: bool = False

class OrchestrationMetadata(BaseModel):
    orchestration_stage: Optional[str] = None
    execution_mode: Optional[str] = Field(None, description="e.g. live, demo, test")
    stage_started_at: Optional[datetime] = None
    stage_completed_at: Optional[datetime] = None
    retry_count: Optional[int] = 0
    dependency_status: Optional[Dict[str, str]] = None
    partial_failure: Optional[bool] = False

class StandardMetadata(BaseModel):
    provenance: Optional[ProvenanceMetadata] = None
    orchestration: Optional[OrchestrationMetadata] = None

class SuccessResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T
    message: Optional[str] = None
    metadata: Optional[StandardMetadata] = None

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail

def success_response(data: Any, message: Optional[str] = None, metadata: Optional[StandardMetadata] = None) -> SuccessResponse[Any]:
    return SuccessResponse(data=data, message=message, metadata=metadata)

def error_response(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> ErrorResponse:
    return ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
