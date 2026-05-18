from fastapi import APIRouter, Depends, Path
from typing import Optional

from app.core.dependencies import get_current_active_user
from app.services.viewer_service import viewer_service

router = APIRouter(prefix="/projects/{project_id}/viewer", tags=["Viewer"])

@router.get("/assets")
async def get_viewer_assets(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Return all visualization-ready assets for the project:
    - protein structures
    - ligand files
    - docking poses
    - GNINA poses
    - simulation trajectories if available
    """
    user_id = str(current_user["_id"])
    data = await viewer_service.get_viewer_assets(project_id, user_id)
    return {
        "success": True,
        "data": data,
        "message": "Viewer assets fetched"
    }

@router.get("/protein/{target_id}")
async def get_protein_metadata(
    project_id: str = Path(...),
    target_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Return protein structure file metadata and download URL for selected target.
    """
    user_id = str(current_user["_id"])
    data = await viewer_service.get_protein_metadata(project_id, target_id, user_id)
    if data is None:
        return {
            "success": True,
            "data": None,
            "message": "No protein structure found for target"
        }
    return {
        "success": True,
        "data": data,
        "message": "Protein structure fetched"
    }

@router.get("/ligand/{molecule_id}")
async def get_ligand_metadata(
    project_id: str = Path(...),
    molecule_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Return ligand structure file metadata or virtual ligand (SMILES) payload.
    """
    user_id = str(current_user["_id"])
    data = await viewer_service.get_ligand_metadata(project_id, molecule_id, user_id)
    return {
        "success": True,
        "data": data,
        "message": "Ligand asset fetched"
    }

@router.get("/pose/{result_id}")
async def get_pose_metadata(
    project_id: str = Path(...),
    result_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Return docking or GNINA pose asset for a result.
    """
    user_id = str(current_user["_id"])
    data = await viewer_service.get_pose_metadata(project_id, result_id, user_id)
    return {
        "success": True,
        "data": data,
        "message": "Pose asset fetched"
    }

@router.get("/interaction-fingerprint/{result_id}")
async def get_interaction_fingerprint(
    project_id: str = Path(...),
    result_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Return interaction fingerprint for docking/GNINA result.
    """
    user_id = str(current_user["_id"])
    data = await viewer_service.get_interaction_fingerprint(project_id, result_id, user_id)
    return {
        "success": True,
        "data": data,
        "message": "Interaction fingerprint fetched"
    }
