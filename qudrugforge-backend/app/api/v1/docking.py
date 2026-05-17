import logging
from typing import Optional
from fastapi import APIRouter, Depends, Body, Path, Query, BackgroundTasks, Request

from app.schemas.docking import (
    CreateDockingRunRequest,
    DockingResultItem,
    PoseFileResponse,
)
from app.schemas.experiment import ExperimentResponse
from app.services.docking_service import docking_service
from app.services.job_simulation_service import run_experiment_simulation
from app.core.dependencies import get_current_active_user

logger = logging.getLogger("qudrugforge-docking-api")

router = APIRouter(prefix="/projects/{project_id}/docking", tags=["Docking"])


# ─── POST /docking/runs ───────────────────────────────────────────────────────

@router.post("/runs", response_model=None)
async def create_docking_run(
    request: Request,
    background_tasks: BackgroundTasks,
    project_id: str = Path(...),
    body: CreateDockingRunRequest = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Create a new docking run.

    Creates an experiment record of type 'docking' with status 'queued'.
    Does NOT execute heavy docking synchronously — this is Phase 10 orchestration.
    Full q-ai-drug execution integration is Phase 20.

    If simulate=true (dev only), background task will advance status through
    queued → running → completed without real scientific output.
    """
    user_id = str(current_user["_id"])

    result = await docking_service.create_docking_run(
        project_id=project_id,
        user_id=user_id,
        target_id=body.target_id,
        compound_selection=body.compound_selection.model_dump(),
        engine=body.engine,
        binding_site=body.binding_site.model_dump() if body.binding_site else None,
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
            "engine": experiment.get("engine"),
            "target_id": body.target_id,
            "molecule_count": result["molecule_count"],
            "binding_site_mode": (
                result["resolved_binding_site"].get("mode", "box")
                if result.get("resolved_binding_site")
                else "box"
            ),
        },
        "message": "Docking run queued",
    }


# ─── GET /docking/runs ────────────────────────────────────────────────────────

@router.get("/runs", response_model=None)
async def list_docking_runs(
    project_id: str = Path(...),
    status: Optional[str] = Query(None, description="Filter by experiment status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user),
):
    """
    List all docking run experiments for this project.
    Returns only experiments with type='docking'.
    """
    user_id = str(current_user["_id"])

    items, total = await docking_service.list_docking_runs(
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
        "message": "Docking runs fetched",
    }


# ─── GET /docking/runs/{experiment_id} ───────────────────────────────────────

@router.get("/runs/{experiment_id}", response_model=None)
async def get_docking_run(
    project_id: str = Path(...),
    experiment_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
):
    """Return detail for a single docking run experiment."""
    user_id = str(current_user["_id"])

    experiment = await docking_service.get_docking_run(
        project_id=project_id,
        experiment_id=experiment_id,
        user_id=user_id,
    )

    serialized = ExperimentResponse.from_mongo(experiment).model_dump()

    return {
        "success": True,
        "data": serialized,
        "message": "Docking run fetched",
    }


# ─── GET /docking/results ─────────────────────────────────────────────────────

@router.get("/results", response_model=None)
async def list_docking_results(
    request: Request,
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None, description="Filter by experiment ID"),
    molecule_id: Optional[str] = Query(None, description="Filter by molecule ID"),
    target_id: Optional[str] = Query(None, description="Filter by target ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("rank", description="Sort field: rank, score, created_at"),
    sort_order: str = Query("asc", description="Sort order: asc | desc"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    List docking results from the docking_results collection.

    Returns both:
    - Results created by docking run experiments (type=docking)
    - Results imported from q-ai-drug docking/results.csv artifacts

    Each result item includes a pose_download_url pointing to the existing
    /api/v1/files/{file_id}/download endpoint.
    """
    user_id = str(current_user["_id"])

    if sort_by not in ("rank", "score", "binding_energy", "binding_affinity_kcal_mol", "created_at", "compound_id"):
        sort_by = "rank"

    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

    items, total = await docking_service.list_docking_results(
        project_id=project_id,
        user_id=user_id,
        experiment_id=experiment_id,
        molecule_id=molecule_id,
        target_id=target_id,
        skip=offset,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    # Build base URL for pose download links
    base_url = str(request.base_url).rstrip("/")

    serialized = []
    for item in items:
        try:
            serialized.append(DockingResultItem.from_mongo(item, base_url).model_dump())
        except Exception as e:
            logger.warning(f"Failed to serialize docking result {item.get('_id')}: {e}")
            continue

    return {
        "success": True,
        "data": {
            "items": serialized,
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "message": "Docking results fetched",
    }


# ─── GET /docking/poses/{pose_id} ────────────────────────────────────────────

@router.get("/poses/{pose_id}", response_model=None)
async def get_docking_pose(
    request: Request,
    project_id: str = Path(...),
    pose_id: str = Path(..., description="The file_id UUID of the pose file"),
    current_user: dict = Depends(get_current_active_user),
):
    """
    Resolve a docking pose file by its file_id UUID.

    Returns file metadata and a download URL consistent with the existing
    /api/v1/files/{file_id}/download pattern.

    The download URL can be used directly to stream the SDF/PDB pose file.
    """
    user_id = str(current_user["_id"])

    meta = await docking_service.get_pose_file_metadata(
        project_id=project_id,
        pose_id=pose_id,
        user_id=user_id,
    )

    base_url = str(request.base_url).rstrip("/")

    serialized = PoseFileResponse.from_mongo(meta, base_url).model_dump()

    return {
        "success": True,
        "data": serialized,
        "message": "Pose file metadata fetched",
    }
