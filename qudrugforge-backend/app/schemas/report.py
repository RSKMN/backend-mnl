from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

class ReportCreate(BaseModel):
    title: Optional[str] = Field(default="EGFR Candidate Dossier")
    report_type: Optional[str] = Field(default="candidate_dossier", alias="type")

    class Config:
        populate_by_name = True

class ReportResponse(BaseModel):
    id: str = Field(..., alias="report_id")
    workspace_id: str
    project_id: str
    title: str
    type: str = Field(..., alias="report_type")
    status: str
    pdf_file_id: Optional[str] = None
    csv_file_id: Optional[str] = None
    sdf_file_id: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = None
    created_at: datetime

    class Config:
        populate_by_name = True

    @classmethod
    def from_mongo(cls, doc: dict):
        return cls(
            report_id=str(doc.get("report_id", "")),
            workspace_id=str(doc.get("workspace_id", "")),
            project_id=str(doc.get("project_id", "")),
            title=doc.get("title", ""),
            report_type=doc.get("report_type", doc.get("type", "candidate_dossier")),
            status=doc.get("status", "ready"),
            pdf_file_id=doc.get("pdf_file_id"),
            csv_file_id=doc.get("csv_file_id"),
            sdf_file_id=doc.get("sdf_file_id"),
            summary=doc.get("summary", {}),
            created_by=str(doc.get("created_by", "")) if doc.get("created_by") else None,
            created_at=doc.get("created_at") or datetime.utcnow()
        )
