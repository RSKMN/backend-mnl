from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


ALLOWED_SOURCE_MOLECULE_SETS = {"filtered", "top_candidates", "selected"}
ALLOWED_ADMET_MODELS = {
    "tox21",
    "clintox",
    "lipinski",
    "herg",
    "ames",
    "hepatotoxicity",
    "cyp",
    "solubility",
    "permeability",
}


class AdmetRunRequest(BaseModel):
    source_molecule_set: str = Field(
        default="filtered",
        description="Source molecule set: filtered | top_candidates | selected",
    )
    molecule_ids: List[str] = Field(default_factory=list)
    models: List[str] = Field(default_factory=lambda: sorted(ALLOWED_ADMET_MODELS))
    name: Optional[str] = None
    simulate: bool = Field(default=False)

    @field_validator("source_molecule_set")
    @classmethod
    def validate_source_molecule_set(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in ALLOWED_SOURCE_MOLECULE_SETS:
            raise ValueError(
                f"source_molecule_set must be one of {sorted(ALLOWED_SOURCE_MOLECULE_SETS)}"
            )
        return normalized

    @field_validator("models")
    @classmethod
    def validate_models(cls, value: List[str]) -> List[str]:
        normalized = [item.lower() for item in value]
        invalid = [item for item in normalized if item not in ALLOWED_ADMET_MODELS]
        if invalid:
            raise ValueError(f"Unsupported ADMET models: {invalid}")
        return normalized

    @model_validator(mode="after")
    def validate_selected_molecules(self) -> "AdmetRunRequest":
        if self.source_molecule_set == "selected" and not self.molecule_ids:
            raise ValueError("molecule_ids must be non-empty when source_molecule_set is selected")
        return self


class AdmetRunCreateResponse(BaseModel):
    experiment_id: str
    status: str
    name: str
    engine: str
    source_molecule_set: str
    molecule_count: Optional[int] = None
    models: List[str]


class AdmetResultResponse(BaseModel):
    id: str
    experiment_id: str
    project_id: str
    workspace_id: str
    molecule_id: Optional[str] = None
    compound_id: Optional[str] = None
    smiles: Optional[str] = None
    toxicity_risk: Optional[str] = None
    risk_level: Optional[str] = None
    risk_score: Optional[float] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    source_file_id: Optional[str] = None
    import_id: Optional[str] = None
    status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw: Dict[str, Any] = Field(default_factory=dict)
    overall_risk: Optional[str] = None
    overall_risk_score: Optional[float] = None
    recommendation: Optional[str] = None
    risk_flags: List[str] = Field(default_factory=list)
    critical_risks: Dict[str, Any] = Field(default_factory=dict)
    radar: Dict[str, Any] = Field(default_factory=dict)
    badges: List[Dict[str, Any]] = Field(default_factory=list)
    table_row: Dict[str, Any] = Field(default_factory=dict)
    ui: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_mongo(cls, doc: dict) -> "AdmetResultResponse":
        data = dict(doc)
        data["id"] = str(data.pop("_id"))

        for field in ("project_id", "workspace_id", "experiment_id", "molecule_id"):
            if field in data and data[field] is not None:
                data[field] = str(data[field])

        if data.get("risk_level") is None:
            data["risk_level"] = data.get("overall_risk") or data.get("toxicity_risk")

        if data.get("risk_score") is None:
            risk = str(data.get("risk_level") or data.get("overall_risk") or "").lower()
            data["risk_score"] = {"low": 0.25, "medium": 0.5, "moderate": 0.5, "high": 0.85}.get(risk)

        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})


class AdmetResultsListResponse(BaseModel):
    items: List[AdmetResultResponse]
    total: int
    limit: int
    offset: int


class AdmetRiskTableResponse(BaseModel):
    items: List[AdmetResultResponse]
    total: int
    limit: int
    offset: int


class AdmetSummaryResponse(BaseModel):
    total: int = 0
    total_molecules: int = 0
    low: int = 0
    medium: int = 0
    moderate: int = 0
    high: int = 0
    unknown: int = 0
    risk_counts: Dict[str, int] = Field(default_factory=dict)
    recommendation_counts: Dict[str, int] = Field(default_factory=dict)
    average_scores: Dict[str, Optional[float]] = Field(default_factory=dict)
    top_warnings: List[Dict[str, Any]] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)

