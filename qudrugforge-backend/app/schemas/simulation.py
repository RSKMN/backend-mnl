from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.simulation_stability import build_simulation_result_payload, build_simulation_trajectory_payload


ALLOWED_SIMULATION_TYPES = {"md"}
ALLOWED_SIMULATION_ENGINES = {"gromacs", "openmm", "q_ai_drug", "imported"}
ALLOWED_SOURCE_EXPERIMENT_TYPES = {"docking", "gnina", "quantum"}


class SimulationRunRequest(BaseModel):
    simulation_type: str = Field(default="md")
    engine: str = Field(default="gromacs")
    source_experiment_id: Optional[str] = Field(default=None)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    name: Optional[str] = Field(default=None)
    simulate: bool = Field(default=False)

    @field_validator("simulation_type")
    @classmethod
    def validate_simulation_type(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in ALLOWED_SIMULATION_TYPES:
            raise ValueError(f"simulation_type must be one of {sorted(ALLOWED_SIMULATION_TYPES)}")
        return normalized

    @field_validator("engine")
    @classmethod
    def validate_engine(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in ALLOWED_SIMULATION_ENGINES:
            raise ValueError(f"engine must be one of {sorted(ALLOWED_SIMULATION_ENGINES)}")
        return normalized

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if "duration" in value:
            try:
                duration_val = float(value["duration"])
                if duration_val <= 0:
                    raise ValueError("duration must be a positive number")
            except (TypeError, ValueError) as exc:
                raise ValueError("duration must be a positive number") from exc
        if "temperature" in value:
            try:
                temp_val = float(value["temperature"])
                if temp_val <= 0:
                    raise ValueError("temperature must be a positive number")
            except (TypeError, ValueError) as exc:
                raise ValueError("temperature must be a positive number") from exc
        return value

    @model_validator(mode="after")
    def validate_source_experiment_id(self) -> "SimulationRunRequest":
        if self.source_experiment_id is not None and not self.source_experiment_id.strip():
            raise ValueError("source_experiment_id must not be empty when provided")
        return self


class SimulationRunCreateResponse(BaseModel):
    experiment_id: str
    status: str
    name: str
    engine: str
    simulation_type: str
    source_experiment_id: Optional[str] = None
    source_experiment_type: Optional[str] = None


class SimulationResultResponse(BaseModel):
    id: str
    experiment_id: str
    project_id: str
    workspace_id: str
    compound_id: Optional[str] = None
    smiles: Optional[str] = None
    md_stability_score: Optional[float] = None
    stability_score: Optional[float] = None
    rmsd: Optional[float] = None
    rmsd_avg: Optional[float] = None
    rmsf: Optional[float] = None
    rmsf_avg: Optional[float] = None
    stability_class: Optional[str] = None
    source_file_id: Optional[str] = None
    trajectory_file_id: Optional[str] = None
    trajectory_download_url: Optional[str] = None
    import_id: Optional[str] = None
    status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_mongo(cls, doc: dict, base_url: str = "") -> "SimulationResultResponse":
        payload = build_simulation_result_payload(doc, base_url)
        return cls(**{key: value for key, value in payload.items() if key in cls.model_fields})


class SimulationResultsListResponse(BaseModel):
    items: List[SimulationResultResponse]
    total: int
    limit: int
    offset: int


class SimulationStabilityResponse(BaseModel):
    total: int
    stable: int
    warning: int
    moderate: int = 0
    unstable: int
    imported: int
    unknown: int = 0
    average_md_stability_score: Optional[float] = None
    average_rmsd: Optional[float] = None
    average_rmsf: Optional[float] = None
    rmsd_avg: Optional[float] = None
    rmsd_max: Optional[float] = None
    rmsf_avg: Optional[float] = None
    rmsf_max: Optional[float] = None
    stability_score: Optional[float] = None
    stability_class: Optional[str] = None
    stability_class_counts: Dict[str, int] = Field(default_factory=dict)
    chart_data: List["SimulationChartPoint"] = Field(default_factory=list)
    top_candidates: List[SimulationResultResponse] = Field(default_factory=list)


class SimulationChartPoint(BaseModel):
    frame_index: int
    time: Optional[float] = None
    rmsd: Optional[float] = None
    rmsf: Optional[float] = None
    stability_score: Optional[float] = None
    stability_class: Optional[str] = None
    trajectory_file_id: Optional[str] = None
    experiment_id: Optional[str] = None


class SimulationTrajectoryResponse(BaseModel):
    file_id: str
    experiment_id: Optional[str] = None
    molecule_id: Optional[str] = None
    target_id: Optional[str] = None
    original_filename: str
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    download_url: str
    viewer_url: Optional[str] = None
    project_id: str
    workspace_id: str
    source_module: Optional[str] = None
    linked_experiment_id: Optional[str] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_mongo(cls, doc: dict, base_url: str = "") -> "SimulationTrajectoryResponse":
        payload = build_simulation_trajectory_payload(doc, base_url)
        return cls(**{key: value for key, value in payload.items() if key in cls.model_fields})


class SimulationTrajectoriesListResponse(BaseModel):
    items: List[SimulationTrajectoryResponse]
    total: int
    limit: int
    offset: int


SimulationStabilityResponse.model_rebuild()