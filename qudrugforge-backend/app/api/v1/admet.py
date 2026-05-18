import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path, Query

from app.core.dependencies import get_current_active_user
from app.schemas.admet import AdmetResultResponse, AdmetRunRequest, AdmetSummaryResponse
from app.services.admet_service import admet_service
from app.services.job_simulation_service import run_experiment_simulation
from app.utils.admet_risk import classify_admet_result

logger = logging.getLogger("qudrugforge-admet-api")

router = APIRouter(prefix="/projects/{project_id}/admet", tags=["ADMET"])


@router.post("/runs", response_model=None)
async def create_admet_run(
    background_tasks: BackgroundTasks,
    project_id: str = Path(...),
    body: AdmetRunRequest = Body(...),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])

    result = await admet_service.create_admet_run(
        project_id=project_id,
        user_id=user_id,
        source_molecule_set=body.source_molecule_set,
        molecule_ids=body.molecule_ids,
        models=body.models,
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
            "engine": experiment.get("engine", "admet"),
            "source_molecule_set": body.source_molecule_set,
            "molecule_count": result["molecule_count"],
            "models": body.models,
        },
        "message": "ADMET run queued",
    }


def _serialize_admet_results(items: list[dict]) -> list[dict]:
    serialized = []
    for item in items:
        try:
            base = AdmetResultResponse.from_mongo(item).model_dump()
            serialized.append({**base, **classify_admet_result(item)})
        except Exception as exc:
            logger.warning("Failed to serialize ADMET result %s: %s", item.get("_id"), exc)
    return serialized


@router.get("/results", response_model=None)
async def list_admet_results(
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])
    items, total = await admet_service.list_admet_results(
        project_id=project_id,
        user_id=user_id,
        experiment_id=experiment_id,
        risk_level=risk_level,
        skip=offset,
        limit=limit,
    )

    return {
        "success": True,
        "data": {
            "items": _serialize_admet_results(items),
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "message": "ADMET results fetched",
    }


@router.get("/risk-table", response_model=None)
async def list_admet_risk_table(
    project_id: str = Path(...),
    experiment_id: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])
    items, total = await admet_service.list_admet_results(
        project_id=project_id,
        user_id=user_id,
        experiment_id=experiment_id,
        risk_level=risk_level,
        skip=offset,
        limit=limit,
    )

    return {
        "success": True,
        "data": {
            "items": _serialize_admet_results(items),
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        "message": "ADMET risk table fetched",
    }


@router.get("/summary", response_model=None)
async def get_admet_summary(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])
    summary = await admet_service.get_admet_summary(project_id=project_id, user_id=user_id)
    return {
        "success": True,
        "data": AdmetSummaryResponse(**summary).model_dump(),
        "message": "ADMET summary fetched",
    }

