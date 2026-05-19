from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class PipelineStageStatus(BaseModel):
    status: str = Field(..., description="Status of the stage: queued, running, completed, failed, cancelled, importing_results, imported")
    progress: int = Field(0, description="Progress percentage: 0 to 100")
    started_at: Optional[datetime] = Field(default=None, description="Timestamp when stage started")
    completed_at: Optional[datetime] = Field(default=None, description="Timestamp when stage finished")
    experiment_id: Optional[str] = Field(default=None, description="ID of the stage experiment document")
    output_artifact_ids: List[str] = Field(default_factory=list, description="List of generated output file file_ids")
    error: Optional[str] = Field(default=None, description="Error trace message if stage failed")

class PipelineRunRequest(BaseModel):
    pipeline: List[str] = Field(
        ..., 
        description="Ordered list of stages to execute: target_ranking, molecule_generation, filtering, docking, gnina, quantum, admet, simulation, report"
    )
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Configuration parameters for pipeline execution")

class PipelineRunResponse(BaseModel):
    id: str = Field(..., description="Unique pipeline execution run ID")
    project_id: str = Field(..., description="Associated project ID")
    workspace_id: str = Field(..., description="Associated workspace ID")
    status: str = Field(..., description="Overall status: queued, running, completed, failed, cancelled")
    pipeline: List[str] = Field(..., description="List of pipeline stages to be executed")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Configuration parameters used")
    stage_statuses: Dict[str, PipelineStageStatus] = Field(default_factory=dict, description="Status trace of each individual stage")
    created_at: datetime = Field(..., description="Timestamp when pipeline run was queued")
    updated_at: datetime = Field(..., description="Timestamp when pipeline run was last updated")

    @classmethod
    def from_mongo(cls, doc: dict):
        if not doc:
            return None
        data = dict(doc)
        data["id"] = str(data["_id"])
        data["project_id"] = str(data["project_id"])
        data["workspace_id"] = str(data["workspace_id"])
        
        stages_raw = data.get("stage_statuses", {})
        stage_statuses = {}
        for stage, val in stages_raw.items():
            if isinstance(val, dict):
                stage_statuses[stage] = PipelineStageStatus(**val)
        data["stage_statuses"] = stage_statuses
        
        return cls(**data)
