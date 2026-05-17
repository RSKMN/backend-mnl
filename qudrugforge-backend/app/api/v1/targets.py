from fastapi import APIRouter, Depends, Body, Path, Query
from typing import Optional
from app.schemas.target import TargetCreate, TargetResponse, TargetRankRequest
from app.services.target_service import target_service
from app.core.dependencies import get_current_active_user

router = APIRouter(prefix="/projects/{project_id}/targets", tags=["Targets"])

@router.get("")
async def list_targets(
    project_id: str = Path(...),
    status: Optional[str] = Query(None, description="Filter by target status"),
    search: Optional[str] = Query(None, description="Search term for gene or UniProt ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    items, total = await target_service.list_targets(
        project_id=project_id,
        status=status,
        search=search,
        skip=offset,
        limit=limit,
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": {
            "items": [TargetResponse.from_mongo(item).model_dump() for item in items],
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Targets fetched"
    }

@router.post("")
async def create_target(
    project_id: str = Path(...),
    request: TargetCreate = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    target = await target_service.create_target(
        project_id=project_id,
        request_data=request.model_dump(exclude_unset=True),
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": TargetResponse.from_mongo(target).model_dump(),
        "message": "Target created successfully"
    }

@router.post("/rank")
async def rank_targets(
    project_id: str = Path(...),
    request: TargetRankRequest = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    ranked = await target_service.rank_targets(
        project_id=project_id,
        request_data=request.model_dump(exclude_unset=True),
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": {
            "items": [TargetResponse.from_mongo(item).model_dump() for item in ranked]
        },
        "message": "Targets ranked"
    }

@router.get("/{target_id}")
async def get_target(
    project_id: str = Path(...),
    target_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    target = await target_service.get_target(project_id, target_id, user_id)
    
    return {
        "success": True,
        "data": TargetResponse.from_mongo(target).model_dump(),
        "message": "Target fetched successfully"
    }
