from pydantic import BaseModel, Field, model_validator
from typing import Optional, Dict, Any, List
from datetime import datetime


# ─── GNINA Parameters ────────────────────────────────────────────────────────

class GninaParameters(BaseModel):
    cnn_scoring: bool = Field(default=True, description="Enable CNN scoring")
    exhaustiveness: int = Field(default=8, ge=1, le=128)
    num_modes: int = Field(default=9, ge=1, le=50)
    cnn_model: Optional[str] = Field(
        default=None,
        description="CNN model name, e.g. cross-docked_default2018"
    )
    cpu: Optional[int] = Field(default=None, ge=1)
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extra GNINA parameters passed through verbatim"
    )


# ─── Create GNINA Run Request ─────────────────────────────────────────────────

class CreateGninaRunRequest(BaseModel):
    source_docking_experiment_id: str = Field(
        ...,
        description="Experiment ID of the completed docking run to rescore"
    )
    top_n: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of top docking candidates to select for GNINA rescoring"
    )
    parameters: GninaParameters = Field(
        default_factory=GninaParameters,
        description="GNINA execution parameters"
    )
    name: Optional[str] = Field(
        default=None,
        description="Optional human-readable name for this run"
    )
    simulate: bool = Field(
        default=False,
        description="[DEV ONLY] If true, simulate status progression in background"
    )

    @model_validator(mode="after")
    def validate_top_n(self) -> "CreateGninaRunRequest":
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        return self


# ─── GNINA Run Create Response ────────────────────────────────────────────────

class GninaRunCreateResponse(BaseModel):
    experiment_id: str
    status: str
    q_ai_drug_job_id: Optional[str] = None


# ─── GNINA Status Response ────────────────────────────────────────────────────

class QAiDrugStatusInfo(BaseModel):
    available: bool
    status: Optional[str] = None
    job_id: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class GninaStatusResponse(BaseModel):
    project_id: str
    experiment_id: Optional[str] = None
    status: str
    progress: int
    q_ai_drug: Optional[QAiDrugStatusInfo] = None
    updated_at: Optional[datetime] = None


# ─── GNINA Log Item ───────────────────────────────────────────────────────────

class GninaLogItem(BaseModel):
    timestamp: Optional[datetime] = None
    level: str = "info"
    message: str
    stage: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── GNINA Result Item ────────────────────────────────────────────────────────

class GninaResultItem(BaseModel):
    id: str
    experiment_id: str
    source_docking_experiment_id: Optional[str] = None
    project_id: str
    workspace_id: str
    molecule_id: Optional[str] = None
    target_id: Optional[str] = None
    compound_id: Optional[str] = None
    smiles: Optional[str] = None
    target_gene: Optional[str] = None

    # CNN scores — canonical names
    cnn_pose_score: Optional[float] = None
    cnn_affinity: Optional[float] = None
    cnn_vs: Optional[float] = None

    # Backward-compat aliases from artifact importer
    cnn_score: Optional[float] = None
    binding_energy: Optional[float] = None

    pose_rank: Optional[int] = None
    rank: Optional[int] = None
    pose_file_id: Optional[str] = None
    pose_download_url: Optional[str] = None

    source: Optional[str] = None
    status: Optional[str] = None
    import_batch_id: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_mongo(cls, doc: dict, base_url: str = "") -> "GninaResultItem":
        data = dict(doc)
        data["id"] = str(data.pop("_id"))

        for field in ("project_id", "workspace_id", "molecule_id",
                      "target_id", "experiment_id", "source_docking_experiment_id"):
            if field in data and data[field] is not None:
                data[field] = str(data[field])

        # Normalize CNN score aliases
        cnn_score = data.get("cnn_score") or data.get("gnina_cnn_score")
        if cnn_score is not None and data.get("cnn_pose_score") is None:
            data["cnn_pose_score"] = cnn_score

        # Normalize affinity aliases
        cnn_aff = (data.get("cnn_affinity") or data.get("gnina_cnn_affinity") or
                   data.get("binding_energy"))
        if cnn_aff is not None and data.get("cnn_affinity") is None:
            data["cnn_affinity"] = cnn_aff

        # Normalize rank
        if data.get("pose_rank") is None and data.get("rank") is not None:
            data["pose_rank"] = data["rank"]

        # Build pose download URL
        pose_file_id = data.get("pose_file_id")
        if pose_file_id:
            data["pose_download_url"] = f"{base_url}/api/v1/files/{pose_file_id}/download"

        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})


class GninaResultsListResponse(BaseModel):
    items: List[GninaResultItem]
    total: int
    limit: int
    offset: int


# ─── Pose File Response (re-use shape from docking) ──────────────────────────

class GninaPoseFileResponse(BaseModel):
    file_id: str
    original_filename: str
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    download_url: str
    project_id: str
    workspace_id: str
    source_module: Optional[str] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_mongo(cls, doc: dict, base_url: str = "") -> "GninaPoseFileResponse":
        return cls(
            file_id=doc["file_id"],
            original_filename=doc.get("original_filename", doc.get("stored_filename", "")),
            file_type=doc.get("file_type"),
            mime_type=doc.get("mime_type"),
            size_bytes=doc.get("size_bytes"),
            download_url=f"{base_url}/api/v1/files/{doc['file_id']}/download",
            project_id=str(doc.get("project_id", "")),
            workspace_id=str(doc.get("workspace_id", "")),
            source_module=doc.get("source_module"),
            created_at=doc.get("created_at"),
        )
