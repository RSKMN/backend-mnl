from fastapi import APIRouter, Depends, Body, Path, Query, BackgroundTasks
from typing import Optional, List

from app.schemas.experiment import (
    ExperimentCreate,
    ExperimentUpdate,
    ExperimentResponse,
    ExperimentListResponse,
    ExperimentLogCreate,
    ExperimentSummaryResponse
)
from app.services.experiment_service import experiment_service
from app.services.job_simulation_service import run_experiment_simulation
from app.core.dependencies import get_current_active_user

router = APIRouter(prefix="/projects/{project_id}/experiments", tags=["Experiments"])

@router.get("", response_model=None)
async def list_experiments(
    project_id: str = Path(...),
    status: Optional[str] = Query(None, description="Filter by status"),
    type: Optional[str] = Query(None, description="Filter by stage/type"),
    engine: Optional[str] = Query(None, description="Filter by engine"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    items, total = await experiment_service.list_experiments(
        project_id=project_id,
        user_id=user_id,
        status=status,
        type_str=type,
        engine_str=engine,
        skip=offset,
        limit=limit
    )

    serialized_items = [ExperimentResponse.from_mongo(item).model_dump() for item in items]
    return {
        "success": True,
        "data": {
            "items": serialized_items,
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Experiments fetched"
    }

@router.post("", response_model=None)
async def create_experiment(
    background_tasks: BackgroundTasks,
    project_id: str = Path(...),
    request: ExperimentCreate = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    created = await experiment_service.create_experiment(
        project_id=project_id,
        user_id=user_id,
        name=request.name,
        type_str=request.type,
        engine_str=request.engine,
        parameters=request.parameters,
        input_file_ids=request.input_file_ids
    )

    experiment_id = str(created["_id"])

    # If simulate=True, launch development background simulation
    if request.simulate:
        background_tasks.add_task(run_experiment_simulation, experiment_id)

    serialized = ExperimentResponse.from_mongo(created).model_dump()
    return {
        "success": True,
        "data": serialized,
        "message": "Experiment created successfully"
    }

@router.get("/summary", response_model=None)
async def get_experiments_summary(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    summary = await experiment_service.get_summary(project_id, user_id)
    return {
        "success": True,
        "data": summary,
        "message": "Experiment summary fetched"
    }

@router.get("/{experiment_id}", response_model=None)
async def get_experiment_detail(
    project_id: str = Path(...),
    experiment_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    experiment = await experiment_service.get_experiment(project_id, experiment_id, user_id)
    serialized = ExperimentResponse.from_mongo(experiment).model_dump()
    return {
        "success": True,
        "data": serialized,
        "message": "Experiment fetched successfully"
    }

@router.patch("/{experiment_id}", response_model=None)
async def update_experiment(
    project_id: str = Path(...),
    experiment_id: str = Path(...),
    request: ExperimentUpdate = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    updated = await experiment_service.update_experiment(
        project_id=project_id,
        experiment_id=experiment_id,
        user_id=user_id,
        data=request.model_dump(exclude_unset=True)
    )
    serialized = ExperimentResponse.from_mongo(updated).model_dump()
    return {
        "success": True,
        "data": serialized,
        "message": "Experiment updated successfully"
    }

@router.get("/{experiment_id}/logs", response_model=None)
async def get_experiment_logs(
    project_id: str = Path(...),
    experiment_id: str = Path(...),
    level: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    # Standard membership + scoping validation
    experiment = await experiment_service.get_experiment(project_id, experiment_id, user_id)
    
    logs = experiment.get("logs", [])
    if level:
        logs = [log for log in logs if log.get("level", "info").lower() == level.lower()]

    # Paginate list of logs
    paginated_logs = logs[offset : offset + limit]
    
    return {
        "success": True,
        "data": {
            "items": paginated_logs,
            "total": len(logs),
            "limit": limit,
            "offset": offset
        },
        "message": "Experiment logs fetched"
    }

@router.post("/{experiment_id}/logs", response_model=None)
async def append_experiment_log(
    project_id: str = Path(...),
    experiment_id: str = Path(...),
    request: ExperimentLogCreate = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    updated = await experiment_service.append_log(
        project_id=project_id,
        experiment_id=experiment_id,
        user_id=user_id,
        log_data=request.model_dump()
    )
    
    serialized = ExperimentResponse.from_mongo(updated).model_dump()
    return {
        "success": True,
        "data": serialized["logs"],
        "message": "Log appended successfully"
    }

@router.post("/{experiment_id}/cancel", response_model=None)
async def cancel_experiment(
    project_id: str = Path(...),
    experiment_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    updated = await experiment_service.cancel_experiment(
        project_id=project_id,
        experiment_id=experiment_id,
        user_id=user_id
    )
    serialized = ExperimentResponse.from_mongo(updated).model_dump()
    return {
        "success": True,
        "data": serialized,
        "message": "Experiment cancelled successfully"
    }
