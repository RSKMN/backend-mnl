from fastapi import APIRouter, Depends, Path, Query, Body
from pydantic import BaseModel
from typing import Optional

from app.core.dependencies import get_current_active_user
from app.services.chemical_space_service import chemical_space_service

router = APIRouter(prefix="/projects/{project_id}/chemical-space", tags=["Chemical Space"])

class ChemicalSpaceRecomputeRequest(BaseModel):
    method: str = "deterministic_placeholder"
    limit: int = 1000
    store: bool = True

@router.get("")
async def get_chemical_space(
    project_id: str = Path(...),
    limit: int = Query(500, ge=1, le=2000),
    status: Optional[str] = Query(None, description="Filter by molecule status"),
    source: Optional[str] = Query(None, description="Filter by molecule source"),
    recompute: bool = Query(False, description="Recompute coordinates on the fly"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Return chemical space points based on real molecule records.
    """
    user_id = str(current_user["_id"])
    data = await chemical_space_service.get_chemical_space(
        project_id=project_id,
        user_id=user_id,
        limit=limit,
        status=status,
        source=source,
        recompute=recompute
    )
    return {
        "success": True,
        "data": data,
        "message": "Chemical space fetched"
    }

@router.post("/recompute")
async def recompute_chemical_space(
    project_id: str = Path(...),
    body: ChemicalSpaceRecomputeRequest = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Recompute/store chemical space coordinates for molecules in project.
    """
    user_id = str(current_user["_id"])
    data = await chemical_space_service.recompute_chemical_space(
        project_id=project_id,
        user_id=user_id,
        method=body.method,
        limit=body.limit,
        store=body.store
    )
    return {
        "success": True,
        "data": data,
        "message": "Chemical space recomputed"
    }
