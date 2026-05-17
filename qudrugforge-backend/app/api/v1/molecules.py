from fastapi import APIRouter, Depends, Body, Path, Query
from typing import Optional
from app.schemas.molecule import (
    MoleculeResponse,
    MoleculeImportRequest,
    MoleculeImportSummary,
    MoleculeFilterRequest,
    MoleculeGenerateRequest
)
from app.services.molecule_service import molecule_service
from app.core.dependencies import get_current_active_user

router = APIRouter(prefix="/projects/{project_id}/molecules", tags=["Molecules"])

@router.get("")
async def list_molecules(
    project_id: str = Path(...),
    status: Optional[str] = Query(None, description="Filter by molecule status"),
    search: Optional[str] = Query(None, description="Search term for compound ID or SMILES"),
    source_file_id: Optional[str] = Query(None, description="Filter by source uploaded file ID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    items, total = await molecule_service.list_molecules(
        project_id=project_id,
        status=status,
        search=search,
        source_file_id=source_file_id,
        skip=offset,
        limit=limit,
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": {
            "items": [MoleculeResponse.from_mongo(item).model_dump() for item in items],
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Molecules fetched"
    }

@router.post("/import")
async def import_molecules(
    project_id: str = Path(...),
    request: MoleculeImportRequest = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    summary = await molecule_service.import_molecules(
        project_id=project_id,
        request_data=request.model_dump(exclude_unset=True),
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": summary,
        "message": "Molecules imported"
    }

@router.post("/generate")
async def generate_molecules(
    project_id: str = Path(...),
    request: MoleculeGenerateRequest = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    # Phase 6: Return clear placeholder response and do not call q-ai-drug
    return {
        "success": True,
        "data": {
            "generated_count": 0,
            "items": []
        },
        "message": "Molecule generation will be connected to q-ai-drug in a later phase"
    }

@router.post("/filter")
async def filter_molecules(
    project_id: str = Path(...),
    request: MoleculeFilterRequest = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    matched = await molecule_service.filter_molecules(
        project_id=project_id,
        criteria=request.model_dump(exclude_unset=True),
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": {
            "items": [MoleculeResponse.from_mongo(item).model_dump() for item in matched],
            "total": len(matched),
            "criteria": request.model_dump(exclude_unset=True)
        },
        "message": "Molecules filtered"
    }

@router.get("/{molecule_id}")
async def get_molecule(
    project_id: str = Path(...),
    molecule_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    molecule = await molecule_service.get_molecule(project_id, molecule_id, user_id)
    
    return {
        "success": True,
        "data": MoleculeResponse.from_mongo(molecule).model_dump(),
        "message": "Molecule fetched successfully"
    }
