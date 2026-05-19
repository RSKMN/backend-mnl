from fastapi import APIRouter, Depends, Body, Path, Query
from typing import Optional, List
from bson import ObjectId

from app.schemas.artifact_import import ArtifactImportRequest
from app.services.artifact_import_service import artifact_import_service
from app.core.dependencies import get_current_active_user
from app.core.exceptions import AppException

# Repositories (for results list routes)
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.repositories.docking_result_repository import docking_result_repository
from app.repositories.gnina_result_repository import gnina_result_repository
from app.repositories.quantum_result_repository import quantum_result_repository
from app.repositories.simulation_result_repository import simulation_result_repository
from app.repositories.admet_result_repository import admet_result_repository
# report_repository is no longer used in this file;
# report routes live in app/api/v1/reports.py (Phase 16A)


router = APIRouter(prefix="/projects/{project_id}", tags=["Q-AI-Drug Import & Results"])

# Membership check helper
async def check_project_and_membership(project_id: str, current_user: dict):
    project = await project_repository.get_project_by_id(project_id)
    if not project:
        raise AppException(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Project not found"
        )
    workspace_id = str(project["workspace_id"])
    membership = await workspace_repository.get_membership(workspace_id, str(current_user["_id"]))
    if not membership:
        raise AppException(
            status_code=403,
            code="WORKSPACE_ACCESS_DENIED",
            message="User is not an active member of this workspace"
        )
    return project

def serialize_doc(doc: dict) -> dict:
    """
    Serializes a MongoDB document dictionary, safely turning
    all BSON ObjectIds to string.
    """
    if not doc:
        return {}
    res = dict(doc)
    if "_id" in res:
        res["_id"] = str(res["_id"])
    for k, v in res.items():
        if isinstance(v, ObjectId):
            res[k] = str(v)
    return res

@router.post("/q-ai-drug/import-artifacts", response_model=None)
async def import_artifacts(
    project_id: str = Path(...),
    request: ArtifactImportRequest = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    summary = await artifact_import_service.import_artifacts(
        project_id=project_id,
        user_id=user_id,
        run_name=request.run_name,
        source_output_dir=request.source_output_dir,
        experiment_id=request.experiment_id
    )
    
    return {
        "success": True,
        "data": summary,
        "message": "q-ai-drug artifacts imported"
    }

@router.get("/docking/results")
async def list_docking_results(
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    await check_project_and_membership(project_id, current_user)
    items, total = await docking_result_repository.list_results(
        project_id=project_id,
        experiment_id=experiment_id,
        skip=offset,
        limit=limit
    )
    return {
        "success": True,
        "data": {
            "items": [serialize_doc(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Docking results fetched"
    }

@router.get("/gnina/results")
async def list_gnina_results(
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    await check_project_and_membership(project_id, current_user)
    items, total = await gnina_result_repository.list_results(
        project_id=project_id,
        experiment_id=experiment_id,
        skip=offset,
        limit=limit
    )
    return {
        "success": True,
        "data": {
            "items": [serialize_doc(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "GNINA results fetched"
    }

@router.get("/quantum/results")
async def list_quantum_results(
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    await check_project_and_membership(project_id, current_user)
    items, total = await quantum_result_repository.list_results(
        project_id=project_id,
        experiment_id=experiment_id,
        skip=offset,
        limit=limit
    )
    return {
        "success": True,
        "data": {
            "items": [serialize_doc(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Quantum results fetched"
    }

@router.get("/simulations/results")
async def list_simulation_results(
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    await check_project_and_membership(project_id, current_user)
    items, total = await simulation_result_repository.list_results(
        project_id=project_id,
        experiment_id=experiment_id,
        skip=offset,
        limit=limit
    )
    return {
        "success": True,
        "data": {
            "items": [serialize_doc(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Simulation results fetched"
    }

@router.get("/admet/results")
async def list_admet_results(
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    await check_project_and_membership(project_id, current_user)
    items, total = await admet_result_repository.list_results(
        project_id=project_id,
        experiment_id=experiment_id,
        skip=offset,
        limit=limit
    )
    return {
        "success": True,
        "data": {
            "items": [serialize_doc(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "ADMET results fetched"
    }

