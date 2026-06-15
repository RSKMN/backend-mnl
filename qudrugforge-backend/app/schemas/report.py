"""
Phase 16A — Report Schemas
Pydantic v2 schemas for report request/response DTOs.
No file generation in this phase — data model only.
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.schemas.base_result import BaseScientificResult

# ---------------------------------------------------------------------------
# Enums / Literals (kept as plain strings to avoid import cycles)
# ---------------------------------------------------------------------------
REPORT_TYPES = (
    "project_summary",
    "candidate_dossier",
    "experiment_report",
    "imported_q_ai_drug",
    "custom",
)

REPORT_STATUSES = (
    "draft",
    "queued",
    "generating",
    "completed",
    "failed",
    "imported",
)

REPORT_SOURCES = ("qudrugforge", "q_ai_drug", "manual_import")

KNOWN_SECTIONS = [
    "overview",
    "targets",
    "candidates",
    "docking",
    "gnina",
    "quantum",
    "admet",
    "simulations",
    "artifacts",
]


# ---------------------------------------------------------------------------
# Request Bodies
# ---------------------------------------------------------------------------

class ReportCreate(BaseModel):
    title: str = Field(default="Candidate Dossier", max_length=250)
    report_type: str = Field(default="candidate_dossier")
    experiment_id: Optional[str] = None
    candidate_molecule_ids: List[str] = Field(default_factory=list)
    target_ids: List[str] = Field(default_factory=list)
    experiment_ids: List[str] = Field(default_factory=list)
    sections_requested: List[str] = Field(default_factory=lambda: list(KNOWN_SECTIONS))


class ReportUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=250)
    candidate_molecule_ids: Optional[List[str]] = None
    target_ids: Optional[List[str]] = None
    sections_requested: Optional[List[str]] = None


class ImportQAiDrugReportRequest(BaseModel):
    source_output_dir: Optional[str] = None
    file_ids: List[str] = Field(default_factory=list)
    title: Optional[str] = Field(default="Imported q-ai-drug Report", max_length=250)

    @model_validator(mode="after")
    def validate_import_params(self):
        if not self.source_output_dir and not self.file_ids:
            raise ValueError("Either 'source_output_dir' or 'file_ids' must be specified.")
        return self


class ReportGenerateRequest(BaseModel):
    formats: List[str] = Field(default_factory=lambda: ["pdf", "html", "csv"])
    include_sections: List[str] = Field(default_factory=lambda: list(KNOWN_SECTIONS))
    top_n: int = Field(default=50, ge=1, le=500)


class ProjectSummaryGenerateRequest(BaseModel):
    title: str = Field(default="Project Summary Report", max_length=250)
    formats: List[str] = Field(default_factory=lambda: ["pdf", "html", "csv"])
    top_n: int = Field(default=50, ge=1, le=500)


class CandidateDossierGenerateRequest(BaseModel):
    title: str = Field(default="Candidate Dossier", max_length=250)
    candidate_molecule_ids: List[str] = Field(default_factory=list)
    formats: List[str] = Field(default_factory=lambda: ["pdf", "html", "csv", "sdf"])
    top_n: int = Field(default=50, ge=1, le=500)


# ---------------------------------------------------------------------------
# Sub-schemas (for nested section structure)
# ---------------------------------------------------------------------------

class ReportSectionDataRefs(BaseModel):
    molecules: List[str] = Field(default_factory=list)
    docking_results: List[str] = Field(default_factory=list)
    gnina_results: List[str] = Field(default_factory=list)
    quantum_results: List[str] = Field(default_factory=list)
    admet_results: List[str] = Field(default_factory=list)
    simulation_results: List[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    section_id: str
    title: str
    status: str = "pending"     # available | missing | pending
    summary: str = ""
    data_refs: ReportSectionDataRefs = Field(default_factory=ReportSectionDataRefs)


class ReportMetadata(BaseModel):
    candidate_count: int = 0
    target_count: int = 0
    has_docking: bool = False
    has_gnina: bool = False
    has_quantum: bool = False
    has_admet: bool = False
    has_simulations: bool = False
    imported_source_dir: Optional[str] = None


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------

class ReportResponse(BaseScientificResult):
    report_id: str
    workspace_id: str
    project_id: str
    title: str
    report_type: str
    source_module: str
    candidate_molecule_ids: List[str] = Field(default_factory=list)
    target_ids: List[str] = Field(default_factory=list)
    experiment_ids: List[str] = Field(default_factory=list)
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    file_ids: List[str] = Field(default_factory=list)
    primary_file_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None
    updated_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    @classmethod
    def from_mongo(cls, doc: dict) -> "ReportResponse":
        data = dict(doc)
        data["report_id"] = str(data.get("report_id", ""))
        data["workspace_id"] = str(data.get("workspace_id", ""))
        data["project_id"] = str(data.get("project_id", ""))
        if data.get("experiment_id"):
            data["experiment_id"] = str(data["experiment_id"])
            
        data["title"] = data.get("title", "")
        data["report_type"] = data.get("report_type", "custom")
        data["source"] = data.get("source", "qudrugforge")
        data["source_module"] = data.get("source_module", "reports")
        data["candidate_molecule_ids"] = data.get("candidate_molecule_ids", [])
        data["target_ids"] = data.get("target_ids", [])
        data["experiment_ids"] = data.get("experiment_ids", [])
        data["sections"] = data.get("sections", [])
        data["file_ids"] = data.get("file_ids", [])
        data["primary_file_id"] = data.get("primary_file_id")
        data["metadata"] = data.get("metadata", {})
        if data.get("created_by"):
            data["created_by"] = str(data["created_by"])
        
        data["created_at"] = data.get("created_at") or datetime.utcnow()
        data["updated_at"] = data.get("updated_at") or datetime.utcnow()
        data["completed_at"] = data.get("completed_at")
        data["error_message"] = data.get("error_message")

        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})


class ReportSummaryResponse(BaseModel):
    project_id: str
    total_reports: int = 0
    completed_reports: int = 0
    draft_reports: int = 0
    imported_reports: int = 0
    failed_reports: int = 0
    available_sections: Dict[str, bool] = Field(default_factory=dict)
