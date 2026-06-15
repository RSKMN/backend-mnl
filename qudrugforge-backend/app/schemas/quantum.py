from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from app.schemas.base_result import BaseScientificResult


ALLOWED_QUANTUM_METHODS = {
    "qml",
    "qm_descriptors",
    "quantum_prefilter",
    "quantum_kernel",
    "reranking",
}


class QuantumParameters(BaseModel):
    method: str = Field(default="qml", description="Quantum/QML method label")
    basis_set: Optional[str] = Field(default=None)
    top_n: Optional[int] = Field(default=None, ge=1, le=1000)
    compute_descriptors: bool = Field(default=True)
    compute_qml_scores: bool = Field(default=True)
    extra: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in ALLOWED_QUANTUM_METHODS:
            raise ValueError(f"method must be one of {sorted(ALLOWED_QUANTUM_METHODS)}")
        return normalized


class CreateQuantumRunRequest(BaseModel):
    source_experiment_id: str = Field(
        ...,
        description="Source docking or GNINA experiment ID to score with quantum/QML",
    )
    parameters: QuantumParameters = Field(default_factory=QuantumParameters)
    name: Optional[str] = Field(default=None)
    simulate: bool = Field(
        default=False,
        description="[DEV ONLY] If true, simulate status progression in background",
    )


class QuantumRunCreateResponse(BaseModel):
    experiment_id: str
    status: str
    name: str
    engine: str
    source_experiment_id: str
    source_experiment_type: str


class QuantumResultItem(BaseScientificResult):
    id: str
    project_id: str
    workspace_id: str
    molecule_id: Optional[str] = None
    compound_id: Optional[str] = None
    smiles: Optional[str] = None
    qm_descriptors: Dict[str, Any] = Field(default_factory=dict)
    homo_ev: Optional[float] = None
    lumo_ev: Optional[float] = None
    gap_ev: Optional[float] = None
    dipole_debye: Optional[float] = None
    quantum_prefilter_score: Optional[float] = None
    prefilter_score: Optional[float] = None
    quantum_kernel_score: Optional[float] = None
    kernel_score: Optional[float] = None
    qml_score: Optional[float] = None
    quantum_rank: Optional[int] = None
    rank: Optional[int] = None
    status: Optional[str] = None
    import_id: Optional[str] = None
    source_file_ids: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None

    @classmethod
    def from_mongo(cls, doc: dict) -> "QuantumResultItem":
        data = dict(doc)
        data["id"] = str(data.pop("_id"))

        for field in ("project_id", "workspace_id", "experiment_id", "molecule_id"):
            if field in data and data[field] is not None:
                data[field] = str(data[field])

        descriptors = data.get("qm_descriptors") or {}
        data["homo_ev"] = data.get("homo_ev", descriptors.get("homo_ev"))
        data["lumo_ev"] = data.get("lumo_ev", descriptors.get("lumo_ev"))
        data["gap_ev"] = data.get("gap_ev", descriptors.get("gap_ev"))
        data["dipole_debye"] = data.get("dipole_debye", descriptors.get("dipole_debye"))
        data["prefilter_score"] = data.get(
            "prefilter_score", data.get("quantum_prefilter_score")
        )
        data["kernel_score"] = data.get("kernel_score", data.get("quantum_kernel_score"))
        if data.get("quantum_rank") is None and data.get("rank") is not None:
            data["quantum_rank"] = data["rank"]

        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})


class QuantumResultsListResponse(BaseModel):
    items: List[QuantumResultItem]
    total: int
    limit: int
    offset: int
