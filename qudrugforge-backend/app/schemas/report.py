"""
Phase 16A — Report Schemas
Pydantic v2 schemas for report request/response DTOs.
No file generation in this phase — data model only.
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

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

class ReportResponse(BaseModel):
    report_id: str
    workspace_id: str
    project_id: str
    experiment_id: Optional[str] = None
    title: str
    report_type: str
    status: str
    source: str
    source_module: str
    candidate_molecule_ids: List[str] = Field(default_factory=list)
    target_ids: List[str] = Field(default_factory=list)
    experiment_ids: List[str] = Field(default_factory=list)
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    file_ids: List[str] = Field(default_factory=list)
    primary_file_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    @classmethod
    def from_mongo(cls, doc: dict) -> "ReportResponse":
        return cls(
            report_id=str(doc.get("report_id", "")),
            workspace_id=str(doc.get("workspace_id", "")),
            project_id=str(doc.get("project_id", "")),
            experiment_id=str(doc["experiment_id"]) if doc.get("experiment_id") else None,
            title=doc.get("title", ""),
            report_type=doc.get("report_type", "custom"),
            status=doc.get("status", "draft"),
            source=doc.get("source", "qudrugforge"),
            source_module=doc.get("source_module", "reports"),
            candidate_molecule_ids=doc.get("candidate_molecule_ids", []),
            target_ids=doc.get("target_ids", []),
            experiment_ids=doc.get("experiment_ids", []),
            sections=doc.get("sections", []),
            file_ids=doc.get("file_ids", []),
            primary_file_id=doc.get("primary_file_id"),
            metadata=doc.get("metadata", {}),
            created_by=str(doc["created_by"]) if doc.get("created_by") else None,
            created_at=doc.get("created_at") or datetime.utcnow(),
            updated_at=doc.get("updated_at") or datetime.utcnow(),
            completed_at=doc.get("completed_at"),
            error_message=doc.get("error_message"),
        )


class ReportSummaryResponse(BaseModel):
    project_id: str
    total_reports: int = 0
    completed_reports: int = 0
    draft_reports: int = 0
    imported_reports: int = 0
    failed_reports: int = 0
    available_sections: Dict[str, bool] = Field(default_factory=dict)
