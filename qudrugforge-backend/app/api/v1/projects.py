from fastapi import APIRouter, Depends, Body, Path, Query
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.schemas.project_input import (
    ProjectInputUpdate,
    BindingSiteUpdate,
    ProjectInputResponse,
    ProjectInputFileAssignment,
    InputCompletenessResponse
)
from app.services.project_service import project_service
from app.services.project_input_service import project_input_service
from app.core.dependencies import get_current_active_user
from app.core.exceptions import AppException

router = APIRouter(tags=["Projects"])

# ==========================================
# Project CRUD Routes
# ==========================================

@router.get("")
async def list_projects(
    workspace_id: str = Query(..., description="The ID of the workspace"),
    status: str = Query(None, description="Filter by project status"),
    search: str = Query(None, description="Search term for project name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    items, total = await project_service.list_projects(
        workspace_id=workspace_id,
        status=status,
        search=search,
        skip=offset,
        limit=limit,
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": {
            "items": [ProjectResponse.from_mongo(item).model_dump() for item in items],
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Projects fetched"
    }

@router.post("")
async def create_project(
    request: ProjectCreate = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    project = await project_service.create_project(
        workspace_id=request.workspace_id,
        name=request.name,
        description=request.description,
        disease_type=request.disease_type,
        cancer_type=request.cancer_type,
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": ProjectResponse.from_mongo(project).model_dump(),
        "message": "Project created successfully"
    }

@router.get("/{project_id}")
async def get_project(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    project = await project_service.get_project(project_id, user_id)
    
    return {
        "success": True,
        "data": ProjectResponse.from_mongo(project).model_dump(),
        "message": "Project fetched successfully"
    }

@router.patch("/{project_id}")
async def update_project(
    project_id: str = Path(...),
    request: ProjectUpdate = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    project = await project_service.update_project(
        project_id=project_id,
        update_data=request.model_dump(exclude_unset=True),
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": ProjectResponse.from_mongo(project).model_dump(),
        "message": "Project updated successfully"
    }

@router.delete("/{project_id}")
async def archive_project(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    await project_service.archive_project(project_id, user_id)
    
    return {
        "success": True,
        "message": "Project archived successfully"
    }

@router.get("/{project_id}/overview")
async def get_project_overview(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    overview = await project_service.get_project_overview(project_id, user_id)
    
    # Serialize project inside the overview
    overview["project"] = ProjectResponse.from_mongo(overview["project"]).model_dump()
    
    return {
        "success": True,
        "data": overview,
        "message": "Project overview fetched"
    }

@router.get("/{project_id}/timeline")
async def get_project_timeline(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    timeline = await project_service.get_project_timeline(project_id, user_id)
    
    return {
        "success": True,
        "data": timeline,
        "message": "Project timeline fetched"
    }

# ==========================================
# Project Inputs Routes
# ==========================================

@router.get("/{project_id}/inputs")
async def get_project_inputs(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    inputs = await project_input_service.get_project_inputs(project_id, user_id)
    
    return {
        "success": True,
        "data": ProjectInputResponse.from_mongo(inputs).model_dump(),
        "message": "Project inputs fetched"
    }

@router.put("/{project_id}/inputs")
async def update_project_inputs(
    project_id: str = Path(...),
    request: ProjectInputUpdate = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    inputs = await project_input_service.update_project_inputs(
        project_id=project_id,
        update_data=request.model_dump(exclude_unset=True),
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": ProjectInputResponse.from_mongo(inputs).model_dump(),
        "message": "Project inputs updated"
    }

@router.patch("/{project_id}/inputs/binding-site")
async def update_binding_site(
    project_id: str = Path(...),
    request: BindingSiteUpdate = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    inputs = await project_input_service.update_binding_site(
        project_id=project_id,
        binding_site_data=request.model_dump(exclude_unset=True),
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": ProjectInputResponse.from_mongo(inputs).model_dump(),
        "message": "Binding site updated"
    }

@router.patch("/{project_id}/inputs/files")
async def assign_files(
    project_id: str = Path(...),
    request: ProjectInputFileAssignment = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    inputs = await project_input_service.assign_files(
        project_id=project_id,
        assignments=request.model_dump(exclude_unset=True),
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": ProjectInputResponse.from_mongo(inputs).model_dump(),
        "message": "Project inputs updated"
    }

@router.get("/{project_id}/inputs/completeness")
async def check_completeness(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    completeness_report = await project_input_service.check_completeness(project_id, user_id)
    
    # Optional schema verification
    validated = InputCompletenessResponse(**completeness_report)
    
    return {
        "success": True,
        "data": validated.model_dump(),
        "message": "Input completeness checked"
    }
