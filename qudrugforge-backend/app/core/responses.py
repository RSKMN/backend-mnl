from typing import Any, Optional, Dict
from fastapi.responses import JSONResponse
from fastapi import status
from pydantic import BaseModel, Field
from datetime import datetime

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

def success_response(data: Any = None, message: str = "Request completed", metadata: Optional[StandardMetadata] = None) -> JSONResponse:
    """
    Constructs a standard structured API success response.
    
    Format:
    {
        "success": true,
        "data": { ... },
        "message": "Request completed",
        "metadata": { ... }
    }
    """
    if data is None:
        data = {}
        
    content = {
        "success": True,
        "data": data,
        "message": message
    }
    
    if metadata:
        content["metadata"] = metadata.model_dump(exclude_none=True)
        
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=content
    )

def error_response(code: str, message: str, details: Optional[Any] = None, status_code: int = status.HTTP_400_BAD_REQUEST) -> JSONResponse:
    """
    Constructs a standard structured API error response.
    
    Format:
    {
        "success": false,
        "error": {
            "code": "ERROR_CODE",
            "message": "Error description",
            "details": { ... }
        }
    }
    """
    if details is None:
        details = {}
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details
            }
        }
    )
