import logging
from typing import Optional
from fastapi import APIRouter, Depends, Body, Path, Query, BackgroundTasks, Request

from app.schemas.gnina import (
    CreateGninaRunRequest,
    GninaResultItem,
    GninaPoseFileResponse,
)
from app.schemas.experiment import ExperimentResponse
from app.services.gnina_service import gnina_service
from app.services.job_simulation_service import run_experiment_simulation
from app.core.dependencies import get_current_active_user

logger = logging.getLogger("qudrugforge-gnina-api")

router = APIRouter(prefix="/projects/{project_id}/gnina", tags=["GNINA"])


# ─── POST /gnina/runs ─────────────────────────────────────────────────────────

@router.post("/runs", response_model=None)
async def create_gnina_run(
    request: Request,
    background_tasks: BackgroundTasks,
    project_id: str = Path(...),
    body: CreateGninaRunRequest = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Start a GNINA CNN rescoring run against a completed docking experiment.

    Creates an experiment record of type 'gnina' with status 'queued'.
    Attempts a non-blocking call to q-ai-drug /research/gnina/start if available.
    If q-ai-drug does not expose that route (current Phase 11 state), the
    experiment stays queued and results flow in via the artifact importer.

    Full q-ai-drug execution orchestration is Phase 20.
    """
    user_id = str(current_user["_id"])

    result = await gnina_service.create_gnina_run(
        project_id=project_id,
        user_id=user_id,
        source_docking_experiment_id=body.source_docking_experiment_id,
        top_n=body.top_n,
        parameters=body.parameters.model_dump(),
        name=body.name,
        simulate=body.simulate,
    )

    experiment = result["experiment"]
    experiment_id = str(experiment["_id"])

    # [DEV ONLY] Optionally simulate lifecycle progression in background
    if body.simulate:
        background_tasks.add_task(run_experiment_simulation, experiment_id)

    return {
        "success": True,
        "data": {
            "experiment_id": experiment_id,
            "status": experiment.get("status", "queued"),
            "name": experiment.get("name"),
            "engine": "gnina",
            "source_docking_experiment_id": body.source_docking_experiment_id,
            "top_n": body.top_n,
            "q_ai_drug_job_id": result["q_ai_drug_job_id"],
        },
        "message": "GNINA run queued",
    }


# ─── GET /gnina/runs ──────────────────────────────────────────────────────────

@router.get("/runs", response_model=None)
async def list_gnina_runs(
    project_id: str = Path(...),
    status: Optional[str] = Query(None, description="Filter by experiment status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user),
):
    """List all GNINA run experiments for this project (type=gnina only)."""
    user_id = str(current_user["_id"])

    items, total = await gnina_service.list_gnina_runs(
        project_id=project_id,
        user_id=user_id,
        status=status,
        skip=offset,
        limit=limit,
    )

    serialized = [ExperimentResponse.from_mongo(item).model_dump() for item in items]

    return {
        "success": True,
        "data": {
            "items": serialized,
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "message": "GNINA runs fetched",
    }


# ─── GET /gnina/runs/{experiment_id} ─────────────────────────────────────────

@router.get("/runs/{experiment_id}", response_model=None)
async def get_gnina_run(
    project_id: str = Path(...),
    experiment_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Return detail for a single GNINA run experiment."""
    user_id = str(current_user["_id"])

    experiment = await gnina_service.get_gnina_run(
        project_id=project_id,
        experiment_id=experiment_id,
        user_id=user_id,
    )

    serialized = ExperimentResponse.from_mongo(experiment).model_dump()

    return {
        "success": True,
        "data": serialized,
        "message": "GNINA run fetched",
    }


# ─── GET /gnina/status ────────────────────────────────────────────────────────

@router.get("/status", response_model=None)
async def get_gnina_status(
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None, description="Filter by experiment ID"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Return GNINA run status for a project.

    If experiment_id is provided, returns that experiment's status plus
    live q-ai-drug status if a q_ai_drug_job_id exists.
    If omitted, returns the latest GNINA experiment status for the project.
    """
    user_id = str(current_user["_id"])

    status_data = await gnina_service.get_gnina_status(
        project_id=project_id,
        user_id=user_id,
        experiment_id=experiment_id,
    )

    return {
        "success": True,
        "data": status_data,
        "message": "GNINA status fetched",
    }


# ─── GET /gnina/logs ──────────────────────────────────────────────────────────

@router.get("/logs", response_model=None)
async def get_gnina_logs(
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None, description="Filter by experiment ID"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Return GNINA logs.

    If experiment_id is provided, returns that experiment's logs merged
    with live q-ai-drug logs (if available).
    If omitted, uses the latest GNINA experiment for the project.
    """
    user_id = str(current_user["_id"])

    logs, total = await gnina_service.get_gnina_logs(
        project_id=project_id,
        user_id=user_id,
        experiment_id=experiment_id,
        skip=offset,
        limit=limit,
    )

    # Serialize log timestamps for JSON
    serialized_logs = []
    for log in logs:
        entry = dict(log)
        ts = entry.get("timestamp")
        if ts and not isinstance(ts, str):
            try:
                entry["timestamp"] = ts.isoformat()
            except Exception:
                entry["timestamp"] = str(ts)
        serialized_logs.append(entry)

    return {
        "success": True,
        "data": {
            "items": serialized_logs,
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "message": "GNINA logs fetched",
    }


# ─── GET /gnina/results ───────────────────────────────────────────────────────

@router.get("/results", response_model=None)
async def list_gnina_results(
    request: Request,
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None, description="Filter by GNINA experiment ID"),
    source_docking_experiment_id: Optional[str] = Query(
        None, description="Filter by source docking experiment ID"
    ),
    molecule_id: Optional[str] = Query(None, description="Filter by molecule ID"),
    target_id: Optional[str] = Query(None, description="Filter by target ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("rank", description="Sort field: rank, cnn_affinity, cnn_pose_score, created_at"),
    sort_order: str = Query("asc", description="Sort order: asc | desc"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    List GNINA results from the gnina_results collection.

    Returns results from both native GNINA runs and q-ai-drug artifact imports.
    Each result includes a pose_download_url pointing to the file download endpoint.
    """
    user_id = str(current_user["_id"])

    VALID_SORT_FIELDS = {"rank", "cnn_affinity", "cnn_pose_score", "cnn_score",
                         "binding_energy", "created_at", "compound_id"}
    if sort_by not in VALID_SORT_FIELDS:
        sort_by = "rank"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

    items, total = await gnina_service.list_gnina_results(
        project_id=project_id,
        user_id=user_id,
        experiment_id=experiment_id,
        source_docking_experiment_id=source_docking_experiment_id,
        molecule_id=molecule_id,
        target_id=target_id,
        skip=offset,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    base_url = str(request.base_url).rstrip("/")
    serialized = []
    for item in items:
        try:
            serialized.append(GninaResultItem.from_mongo(item, base_url).model_dump())
        except Exception as e:
            logger.warning(f"Failed to serialize gnina result {item.get('_id')}: {e}")
            continue

    return {
        "success": True,
        "data": {
            "items": serialized,
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "message": "GNINA results fetched",
    }


# ─── GET /gnina/poses/{pose_id} ───────────────────────────────────────────────

@router.get("/poses/{pose_id}", response_model=None)
async def get_gnina_pose(
    request: Request,
    project_id: str = Path(...),
    pose_id: str = Path(..., description="The file_id UUID of the GNINA pose file"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Resolve a GNINA pose file by its file_id UUID.

    Returns file metadata and a download URL consistent with
    GET /api/v1/files/{file_id}/download.
    """
    user_id = str(current_user["_id"])

    meta = await gnina_service.get_pose_file_metadata(
        project_id=project_id,
        pose_id=pose_id,
        user_id=user_id,
    )

    base_url = str(request.base_url).rstrip("/")
    serialized = GninaPoseFileResponse.from_mongo(meta, base_url).model_dump()

    return {
        "success": True,
        "data": serialized,
        "message": "GNINA pose file metadata fetched",
    }
