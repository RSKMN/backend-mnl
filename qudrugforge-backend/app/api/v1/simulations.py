import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path, Query, Request

from app.core.dependencies import get_current_active_user
from app.schemas.experiment import ExperimentResponse
from app.schemas.simulation import (
    SimulationResultResponse,
    SimulationRunRequest,
    SimulationStabilityResponse,
    SimulationTrajectoryResponse,
)
from app.services.job_simulation_service import run_experiment_simulation
from app.services.simulation_service import simulation_service


logger = logging.getLogger("qudrugforge-simulations-api")

router = APIRouter(prefix="/projects/{project_id}/simulations", tags=["Simulations"])


@router.post("/runs", response_model=None)
async def create_simulation_run(
    background_tasks: BackgroundTasks,
    project_id: str = Path(...),
    body: SimulationRunRequest = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])

    result = await simulation_service.create_simulation_run(
        project_id=project_id,
        user_id=user_id,
        simulation_type=body.simulation_type,
        engine=body.engine,
        source_experiment_id=body.source_experiment_id,
        parameters=body.parameters,
        name=body.name,
        simulate=body.simulate,
    )

    experiment = result["experiment"]
    experiment_id = str(experiment["_id"])

    if body.simulate:
        background_tasks.add_task(run_experiment_simulation, experiment_id)

    return {
        "success": True,
        "data": {
            "experiment_id": experiment_id,
            "status": experiment.get("status", "queued"),
            "name": experiment.get("name"),
            "engine": experiment.get("engine"),
            "simulation_type": body.simulation_type,
            "source_experiment_id": body.source_experiment_id,
            "source_experiment_type": result.get("source_experiment_type"),
        },
        "message": "Simulation run queued",
    }


@router.get("/results", response_model=None)
async def list_simulation_results(
    request: Request,
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])
    items, total = await simulation_service.list_simulation_results(
        project_id=project_id,
        user_id=user_id,
        experiment_id=experiment_id,
        skip=offset,
        limit=limit,
    )
    base_url = str(request.base_url).rstrip("/")

    serialized = []
    for item in items:
        try:
            serialized.append(SimulationResultResponse.from_mongo(item, base_url).model_dump())
        except Exception as exc:
            logger.warning("Failed to serialize simulation result %s: %s", item.get("_id"), exc)

    return {
        "success": True,
        "data": {
            "items": serialized,
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "message": "Simulation results fetched",
    }


@router.get("/stability", response_model=None)
async def get_simulation_stability(
    request: Request,
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])
    summary = await simulation_service.get_simulation_stability(
        project_id=project_id,
        user_id=user_id,
        experiment_id=experiment_id,
    )
    base_url = str(request.base_url).rstrip("/")

    serialized_top_candidates = []
    for item in summary.get("top_candidates", []):
        try:
            serialized_top_candidates.append(SimulationResultResponse.from_mongo(item, base_url).model_dump())
        except Exception as exc:
            logger.warning("Failed to serialize simulation stability candidate %s: %s", item.get("_id"), exc)

    payload = dict(summary)
    payload["top_candidates"] = serialized_top_candidates

    return {
        "success": True,
        "data": SimulationStabilityResponse(**payload).model_dump(),
        "message": "Simulation stability summary fetched",
    }


@router.get("/trajectories", response_model=None)
async def list_simulation_trajectories(
    request: Request,
    project_id: str = Path(...),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])
    items, total = await simulation_service.list_simulation_trajectories(
        project_id=project_id,
        user_id=user_id,
        skip=offset,
        limit=limit,
    )
    base_url = str(request.base_url).rstrip("/")

    return {
        "success": True,
        "data": {
            "items": [SimulationTrajectoryResponse.from_mongo(item, base_url).model_dump() for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "message": "Simulation trajectories fetched",
    }


@router.get("/trajectories/{file_id}", response_model=None)
async def get_simulation_trajectory(
    request: Request,
    project_id: str = Path(...),
    file_id: str = Path(..., description="The file_id UUID of the trajectory file"),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])
    meta = await simulation_service.get_simulation_trajectory_file_metadata(
        project_id=project_id,
        user_id=user_id,
        file_id=file_id,
    )

    base_url = str(request.base_url).rstrip("/")

    return {
        "success": True,
        "data": SimulationTrajectoryResponse.from_mongo(meta, base_url).model_dump(),
        "message": "Simulation trajectory file metadata fetched",
    }