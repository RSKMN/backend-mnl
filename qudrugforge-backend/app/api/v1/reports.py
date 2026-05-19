"""
Phase 16A — Reports API Router

Routes implemented:
  GET    /api/v1/projects/{project_id}/reports/summary
  POST   /api/v1/projects/{project_id}/reports/import-q-ai-drug
  POST   /api/v1/projects/{project_id}/reports/generate-project-summary
  POST   /api/v1/projects/{project_id}/reports/generate-candidate-dossier
  GET    /api/v1/projects/{project_id}/reports
  POST   /api/v1/projects/{project_id}/reports
  GET    /api/v1/projects/{project_id}/reports/{report_id}
  PATCH  /api/v1/projects/{project_id}/reports/{report_id}
  DELETE /api/v1/projects/{project_id}/reports/{report_id}
  POST   /api/v1/projects/{project_id}/reports/{report_id}/generate
  POST   /api/v1/projects/{project_id}/reports/{report_id}/queue-generation
  GET    /api/v1/projects/{project_id}/reports/{report_id}/files

IMPORTANT:
  /summary and /import-q-ai-drug are declared BEFORE /{report_id} so FastAPI
  does not mistakenly treat them as report_id path values.

No file generation in Phase 16A.
"""
import logging
from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, Body, Path, Query

from app.schemas.report import (
    CandidateDossierGenerateRequest,
    ImportQAiDrugReportRequest,
    ProjectSummaryGenerateRequest,
    ReportCreate,
    ReportGenerateRequest,
    ReportUpdate,
)
from app.services.report_generation_service import report_generation_service
from app.services.report_service import report_service
from app.core.dependencies import get_current_active_user
from app.core.exceptions import AppException

logger = logging.getLogger("qudrugforge-reports-api")

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["Reports"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(doc: dict) -> dict:
    """Recursively stringify ObjectId values in a MongoDB document."""
    if not doc:
        return {}
    result = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            result[k] = str(v)
        elif isinstance(v, dict):
            result[k] = _serialize(v)
        elif isinstance(v, list):
            result[k] = [_serialize(i) if isinstance(i, dict) else (str(i) if isinstance(i, ObjectId) else i) for i in v]
        else:
            result[k] = v
    # Always stringify _id
    if "_id" in result:
        result["_id"] = str(result["_id"])
    return result


def _generation_response(result: dict, message: str) -> dict:
    return {
        "success": result["success"],
        "data": {
            "report": _serialize(result["report"]),
            "generated_files": result["generated_files"],
            "warnings": result["warnings"],
        },
        "message": message,
    }


# ---------------------------------------------------------------------------
# STATIC ROUTES — must come before /{report_id}
# ---------------------------------------------------------------------------

@router.get("/summary")
async def get_report_summary(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Return report dashboard summary including available sections
    based on real MongoDB counts. No fake data.
    """
    user_id = str(current_user["_id"])
    summary = await report_service.get_project_report_summary(project_id, user_id)
    return {
        "success": True,
        "data": summary,
        "message": "Report summary fetched",
    }


@router.post("/import-q-ai-drug")
async def import_q_ai_drug_report(
    project_id: str = Path(...),
    request: ImportQAiDrugReportRequest = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Register already-imported q-ai-drug report.pdf / report.html artifacts
    as an imported_q_ai_drug report record.

    Does NOT generate any files.
    Requires that file metadata already exists (artifact importer must have run first).
    Deduplicates by source_output_dir to avoid re-registering the same run.
    """
    user_id = str(current_user["_id"])
    report = await report_service.import_q_ai_drug_report(
        project_id=project_id,
        user_id=user_id,
        title=request.title,
        source_output_dir=request.source_output_dir,
        explicit_file_ids=request.file_ids,
    )
    return {
        "success": True,
        "data": _serialize(report),
        "message": "q-ai-drug report artifacts registered successfully",
    }


@router.post("/generate-project-summary")
async def generate_project_summary(
    project_id: str = Path(...),
    request: ProjectSummaryGenerateRequest = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Create a project_summary report and synchronously generate requested files.
    """
    user_id = str(current_user["_id"])
    result = await report_generation_service.create_and_generate_project_summary(
        project_id=project_id,
        user_id=user_id,
        title=request.title,
        formats=request.formats,
        top_n=request.top_n,
    )
    return _generation_response(result, "Project summary report generated successfully")


@router.post("/generate-candidate-dossier")
async def generate_candidate_dossier(
    project_id: str = Path(...),
    request: CandidateDossierGenerateRequest = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Create a candidate_dossier report and synchronously generate requested files.
    """
    user_id = str(current_user["_id"])
    result = await report_generation_service.create_and_generate_candidate_dossier(
        project_id=project_id,
        user_id=user_id,
        title=request.title,
        candidate_molecule_ids=request.candidate_molecule_ids,
        formats=request.formats,
        top_n=request.top_n,
    )
    return _generation_response(result, "Candidate dossier report generated successfully")


# ---------------------------------------------------------------------------
# COLLECTION ROUTES
# ---------------------------------------------------------------------------

@router.get("")
async def list_reports(
    project_id: str = Path(...),
    report_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user),
):
    """
    List all reports for a project.
    Supports filtering by report_type and status.
    """
    user_id = str(current_user["_id"])
    items, total = await report_service.list_reports(
        project_id=project_id,
        user_id=user_id,
        report_type=report_type,
        status=status,
        skip=skip,
        limit=limit,
    )
    return {
        "success": True,
        "data": {
            "project_id": project_id,
            "reports": [_serialize(r) for r in items],
            "count": total,
            "total": total,
            "limit": limit,
            "skip": skip,
        },
        "message": "Reports fetched",
    }


@router.post("")
async def create_report(
    project_id: str = Path(...),
    request: ReportCreate = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Create a draft report with section availability pre-computed from DB.
    No file generation happens here.
    """
    user_id = str(current_user["_id"])
    report = await report_service.create_report(
        project_id=project_id,
        user_id=user_id,
        title=request.title,
        report_type=request.report_type,
        experiment_id=request.experiment_id,
        candidate_molecule_ids=request.candidate_molecule_ids,
        target_ids=request.target_ids,
        experiment_ids=request.experiment_ids,
        sections_requested=request.sections_requested,
    )
    return {
        "success": True,
        "data": _serialize(report),
        "message": "Report draft created successfully",
    }


# ---------------------------------------------------------------------------
# ITEM ROUTES — /{report_id}
# ---------------------------------------------------------------------------

@router.get("/{report_id}")
async def get_report(
    project_id: str = Path(...),
    report_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Fetch full report metadata by report_id."""
    user_id = str(current_user["_id"])
    report = await report_service.get_report(project_id, report_id, user_id)
    return {
        "success": True,
        "data": _serialize(report),
        "message": "Report fetched successfully",
    }


@router.patch("/{report_id}")
async def update_report(
    project_id: str = Path(...),
    report_id: str = Path(...),
    request: ReportUpdate = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Update safe fields: title, candidate_molecule_ids, target_ids, sections_requested.
    Status transitions are handled by dedicated sub-routes only.
    """
    user_id = str(current_user["_id"])
    report = await report_service.update_report(
        project_id=project_id,
        report_id=report_id,
        user_id=user_id,
        update_data=request.model_dump(exclude_unset=True),
    )
    return {
        "success": True,
        "data": _serialize(report),
        "message": "Report updated",
    }


@router.delete("/{report_id}")
async def delete_report(
    project_id: str = Path(...),
    report_id: str = Path(...),
    delete_files: bool = Query(False, description="Also delete associated files"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Delete report metadata. By default linked files are preserved.
    Pass ?delete_files=true to also remove associated file records.
    """
    user_id = str(current_user["_id"])
    deleted = await report_service.delete_report(
        project_id=project_id,
        report_id=report_id,
        user_id=user_id,
        delete_files=delete_files,
    )
    return {
        "success": deleted,
        "message": "Report deleted" if deleted else "Report not found",
    }


@router.post("/{report_id}/generate")
async def generate_report(
    project_id: str = Path(...),
    report_id: str = Path(...),
    request: ReportGenerateRequest = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Generate CSV/SDF/HTML/PDF files for an existing report from persisted backend data.
    Generation is synchronous in Phase 16B.
    """
    user_id = str(current_user["_id"])
    result = await report_generation_service.generate_report(
        project_id=project_id,
        report_id=report_id,
        user_id=user_id,
        formats=request.formats,
        include_sections=request.include_sections,
        top_n=request.top_n,
    )
    return _generation_response(result, "Report generated successfully")


@router.post("/{report_id}/queue-generation")
async def queue_generation(
    project_id: str = Path(...),
    report_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Mark a draft or failed report as queued for Phase 16B generation.
    imported_q_ai_drug reports cannot be queued.
    """
    user_id = str(current_user["_id"])
    report = await report_service.queue_generation(project_id, report_id, user_id)
    return {
        "success": True,
        "data": _serialize(report),
        "message": "Report queued for generation",
    }


@router.get("/{report_id}/files")
async def get_report_files(
    project_id: str = Path(...),
    report_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Return file metadata + download URLs for all files linked to a report.
    Download happens via the existing /api/v1/files/{file_id}/download endpoint.
    """
    user_id = str(current_user["_id"])
    files = await report_service.get_report_files(project_id, report_id, user_id)
    return {
        "success": True,
        "data": {
            "report_id": report_id,
            "files": files,
        },
        "message": "Report files fetched",
    }
