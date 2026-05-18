from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from datetime import datetime

ALLOWED_TYPES = {
    "target_ranking", "molecule_generation", "molecule_filtering", "docking",
    "gnina", "quantum", "simulation", "admet", "report", "q_ai_drug_import",
    "full_pipeline", "other"
}

ALLOWED_ENGINES = {
    "vina", "gnina", "q_ai_drug", "rdkit", "quantum", "qml", "md", "admet",
    "gromacs", "openmm", "imported",
    "internal", "manual", "other"
}

ALLOWED_STATUSES = {
    "queued", "running", "completed", "failed", "cancelled", "imported"
}

ALLOWED_LOG_LEVELS = {
    "debug", "info", "warning", "error"
}

class ExperimentLogCreate(BaseModel):
    level: str = Field(default="info", description="Log level: debug, info, warning, error")
    message: str = Field(..., description="Details log trace message text")
    stage: Optional[str] = Field(default=None, description="Current workflow stage context")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata trace tags")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        if v.lower() not in ALLOWED_LOG_LEVELS:
            raise ValueError(f"level must be one of {list(ALLOWED_LOG_LEVELS)}")
        return v.lower()

class ExperimentLogResponse(BaseModel):
    timestamp: datetime
    level: str
    message: str
    stage: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ExperimentCreate(BaseModel):
    name: str = Field(..., description="Unique user-friendly name for this experiment")
    type: str = Field(..., description="Experiment type / stage identifier")
    engine: str = Field(..., description="Engine tool used for execution")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Run-specific inputs and config parameters")
    input_file_ids: List[str] = Field(default_factory=list, description="IDs of input files linked to this experiment")
    simulate: bool = Field(default=False, description="Whether to simulate the run lifecycle")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ALLOWED_TYPES:
            raise ValueError(f"type must be one of {list(ALLOWED_TYPES)}")
        return v

    @field_validator("engine")
    @classmethod
    def validate_engine(cls, v: str) -> str:
        if v not in ALLOWED_ENGINES:
            raise ValueError(f"engine must be one of {list(ALLOWED_ENGINES)}")
        return v

class ExperimentUpdate(BaseModel):
    name: Optional[str] = Field(default=None)
    type: Optional[str] = Field(default=None)
    engine: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    progress: Optional[int] = Field(default=None)
    parameters: Optional[Dict[str, Any]] = Field(default=None)
    output_file_ids: Optional[List[str]] = Field(default=None)
    q_ai_drug_job_id: Optional[str] = Field(default=None)
    q_ai_drug_run_name: Optional[str] = Field(default=None)
    import_id: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALLOWED_TYPES:
            raise ValueError(f"type must be one of {list(ALLOWED_TYPES)}")
        return v

    @field_validator("engine")
    @classmethod
    def validate_engine(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALLOWED_ENGINES:
            raise ValueError(f"engine must be one of {list(ALLOWED_ENGINES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {list(ALLOWED_STATUSES)}")
        return v

    @field_validator("progress")
    @classmethod
    def validate_progress(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("progress must be between 0 and 100")
        return v

class ExperimentResponse(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    name: str
    type: str
    engine: str
    status: str
    progress: int
    parameters: Dict[str, Any] = Field(default_factory=dict)
    input_file_ids: List[str] = Field(default_factory=list)
    output_file_ids: List[str] = Field(default_factory=list)
    logs: List[ExperimentLogResponse] = Field(default_factory=list)
    q_ai_drug_job_id: Optional[str] = None
    q_ai_drug_run_name: Optional[str] = None
    import_id: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mongo(cls, doc: dict):
        if not doc:
            return None
        data = dict(doc)
        data["id"] = str(data["_id"])
        
        # Serialize ObjectIds to string
        for field in ["project_id", "workspace_id", "created_by"]:
            if field in data and data[field]:
                data[field] = str(data[field])
                
        # Format logs inside document
        formatted_logs = []
        for log in data.get("logs", []):
            if isinstance(log, dict):
                formatted_logs.append(ExperimentLogResponse(**log))
        data["logs"] = formatted_logs
        
        return cls(**data)

class ExperimentListResponse(BaseModel):
    items: List[ExperimentResponse]
    total: int
    limit: int
    offset: int

class ExperimentSummaryResponse(BaseModel):
    total: int
    queued: int
    running: int
    completed: int
    failed: int
    cancelled: int
    imported: int
    active: int
