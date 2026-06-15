from pydantic import BaseModel, Field, model_validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from app.schemas.base_result import BaseScientificResult


# ─── Binding Site ─────────────────────────────────────────────────────────────

class DockingBindingSiteBox(BaseModel):
    center_x: float = 0.0
    center_y: float = 0.0
    center_z: float = 0.0
    size_x: float = 20.0
    size_y: float = 20.0
    size_z: float = 20.0


class DockingBindingSite(BaseModel):
    mode: str = "box"
    box: Optional[DockingBindingSiteBox] = None
    residues: Optional[List[str]] = None


# ─── Compound Selection ───────────────────────────────────────────────────────

class CompoundSelection(BaseModel):
    mode: str = Field(
        default="all",
        description="Compound selection mode: all | filtered | selected"
    )
    molecule_ids: List[str] = Field(
        default_factory=list,
        description="Required when mode='selected'"
    )

    @model_validator(mode="after")
    def validate_selection(self) -> "CompoundSelection":
        if self.mode not in ("all", "filtered", "selected"):
            raise ValueError("compound_selection.mode must be 'all', 'filtered', or 'selected'")
        if self.mode == "selected" and not self.molecule_ids:
            raise ValueError(
                "molecule_ids must be provided and non-empty when compound_selection.mode is 'selected'"
            )
        return self


# ─── Docking Parameters ───────────────────────────────────────────────────────

class DockingParameters(BaseModel):
    exhaustiveness: int = Field(default=8, ge=1, le=128)
    num_modes: int = Field(default=9, ge=1, le=50)
    energy_range: float = Field(default=3.0, ge=0.0)
    cpu: Optional[int] = Field(default=None, ge=1)
    seed: Optional[int] = None


# ─── Create Docking Run Request ───────────────────────────────────────────────

class CreateDockingRunRequest(BaseModel):
    target_id: str = Field(..., description="ID of the target to dock against")
    compound_selection: CompoundSelection = Field(
        default_factory=CompoundSelection,
        description="Which molecules to include in this docking run"
    )
    engine: str = Field(default="vina", description="Docking engine: vina")
    binding_site: Optional[DockingBindingSite] = Field(
        default=None,
        description="Override binding site; falls back to project_inputs if omitted"
    )
    parameters: DockingParameters = Field(
        default_factory=DockingParameters,
        description="Docking execution parameters"
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
    def validate_engine(self) -> "CreateDockingRunRequest":
        if self.engine not in ("vina",):
            raise ValueError("engine must be 'vina'")
        return self


# ─── Docking Run Response (wraps Experiment) ─────────────────────────────────

class DockingRunCreateResponse(BaseModel):
    experiment_id: str
    status: str
    name: str
    engine: str
    target_id: str
    molecule_count: int
    binding_site_mode: str


# ─── Docking Result Item ──────────────────────────────────────────────────────

class DockingResultItem(BaseScientificResult):
    id: str
    project_id: str
    workspace_id: str
    molecule_id: Optional[str] = None
    target_id: Optional[str] = None
    compound_id: Optional[str] = None
    smiles: Optional[str] = None
    target_gene: Optional[str] = None
    binding_affinity_kcal_mol: Optional[float] = None
    score: Optional[float] = None
    pose_rank: Optional[int] = None
    rank: Optional[int] = None
    pose_file_id: Optional[str] = None
    pose_download_url: Optional[str] = None
    interaction_fingerprint: Dict[str, Any] = Field(default_factory=dict)
    status: Optional[str] = None
    import_batch_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None

    @classmethod
    def from_mongo(cls, doc: dict, base_url: str = "") -> "DockingResultItem":
        data = dict(doc)
        data["id"] = str(data["_id"])

        for field in ("project_id", "workspace_id", "molecule_id", "target_id", "experiment_id"):
            if field in data and data[field] is not None:
                data[field] = str(data[field])

        # Normalize affinity fields
        if "binding_energy" in data and data.get("binding_affinity_kcal_mol") is None:
            data["binding_affinity_kcal_mol"] = data.get("binding_energy") or data.get("score")

        if "score" in data and data.get("binding_affinity_kcal_mol") is None:
            data["binding_affinity_kcal_mol"] = data.get("score")

        # Normalize rank fields
        if "rank" in data and data.get("pose_rank") is None:
            data["pose_rank"] = data.get("rank")

        # Build pose download URL if pose_file_id is present
        pose_file_id = data.get("pose_file_id")
        if pose_file_id:
            data["pose_download_url"] = f"{base_url}/api/v1/files/{pose_file_id}/download"

        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})


class DockingResultsListResponse(BaseModel):
    items: List[DockingResultItem]
    total: int
    limit: int
    offset: int


# ─── Pose File Resolve Response ───────────────────────────────────────────────

class PoseFileResponse(BaseModel):
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
    def from_mongo(cls, doc: dict, base_url: str = "") -> "PoseFileResponse":
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
            created_at=doc.get("created_at")
        )
