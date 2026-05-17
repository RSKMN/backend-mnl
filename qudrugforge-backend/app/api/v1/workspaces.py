from fastapi import APIRouter, Depends, Body, Path
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse
from app.services.workspace_service import workspace_service
from app.core.dependencies import get_current_active_user, require_workspace_member

router = APIRouter(tags=["Workspaces"])

@router.get("")
async def get_workspaces(current_user: dict = Depends(get_current_active_user)):
    user_id = str(current_user["_id"])
    workspaces = await workspace_service.get_user_workspaces(user_id)
    
    return {
        "success": True,
        "data": [WorkspaceResponse.from_mongo(ws, ws["role"]).model_dump() for ws in workspaces],
        "message": "Workspaces fetched successfully"
    }

@router.post("")
async def create_workspace(
    request: WorkspaceCreate = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    workspace = await workspace_service.create_workspace(request.name, user_id)
    
    return {
        "success": True,
        "data": WorkspaceResponse.from_mongo(workspace, workspace["role"]).model_dump(),
        "message": "Workspace created successfully"
    }

@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
    membership: dict = Depends(require_workspace_member())
):
    user_id = str(current_user["_id"])
    workspace = await workspace_service.get_workspace(workspace_id, user_id)
    
    return {
        "success": True,
        "data": WorkspaceResponse.from_mongo(workspace, workspace["role"]).model_dump(),
        "message": "Workspace fetched successfully"
    }

@router.post("/{workspace_id}/select")
async def select_workspace(
    workspace_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
    membership: dict = Depends(require_workspace_member())
):
    user_id = str(current_user["_id"])
    workspace = await workspace_service.get_workspace(workspace_id, user_id)
    
    return {
        "success": True,
        "data": WorkspaceResponse.from_mongo(workspace, workspace["role"]).model_dump(),
        "message": "Workspace selected successfully"
    }
