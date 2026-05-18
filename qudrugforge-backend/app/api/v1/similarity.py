from fastapi import APIRouter, Depends, Path, Query, Body
from pydantic import BaseModel
from typing import Optional

from app.core.dependencies import get_current_active_user
from app.services.similarity_service import similarity_service

router = APIRouter(prefix="/projects/{project_id}/similarity", tags=["Similarity"])

class SimilaritySearchRequest(BaseModel):
    query_molecule_id: Optional[str] = None
    query_smiles: Optional[str] = None
    top_k: int = 20
    min_similarity: float = 0.0
    include_self: bool = False

@router.post("/search")
async def similarity_search(
    project_id: str = Path(...),
    body: SimilaritySearchRequest = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Search similar molecules using backend molecule records.
    """
    user_id = str(current_user["_id"])
    data = await similarity_service.search_similar_molecules(
        project_id=project_id,
        user_id=user_id,
        query_molecule_id=body.query_molecule_id,
        query_smiles=body.query_smiles,
        top_k=body.top_k,
        min_similarity=body.min_similarity,
        include_self=body.include_self
    )
    return {
        "success": True,
        "data": data,
        "message": "Similarity search completed"
    }

@router.get("/matrix")
async def get_similarity_matrix(
    project_id: str = Path(...),
    limit: int = Query(50, ge=1, le=200),
    molecule_ids: Optional[str] = Query(None, description="Optional comma-separated list of molecule IDs"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Return pairwise similarity matrix for a limited set of molecules.
    """
    user_id = str(current_user["_id"])
    data = await similarity_service.get_similarity_matrix(
        project_id=project_id,
        user_id=user_id,
        limit=limit,
        molecule_ids=molecule_ids
    )
    return {
        "success": True,
        "data": data,
        "message": "Similarity matrix fetched"
    }
