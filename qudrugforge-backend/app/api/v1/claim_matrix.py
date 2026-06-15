import logging
from fastapi import APIRouter, Depends, Path
from app.core.dependencies import get_current_active_user
from app.schemas.claim_matrix import ClaimMatrixEntry, ClaimMatrixListResponse, ClaimMatrixSummary
from app.services.claim_matrix_service import claim_matrix_service

logger = logging.getLogger("qudrugforge-claim-matrix-api")

router = APIRouter(prefix="/projects/{project_id}/claim-matrix", tags=["Claim Matrix"])

@router.get("", response_model=None)
async def get_claim_matrix(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])
    items, total = await claim_matrix_service.get_project_claim_matrix(
        project_id=project_id,
        user_id=user_id,
    )

    serialized = []
    for item in items:
        try:
            serialized.append(ClaimMatrixEntry.from_mongo(item).model_dump())
        except Exception as exc:
            logger.warning("Failed to serialize Claim Matrix result %s: %s", item.get("_id"), exc)

    return {
        "success": True,
        "data": {
            "items": serialized,
            "total": total,
        },
        "message": "Claim matrix fetched",
    }

@router.get("/summary", response_model=None)
async def get_claim_matrix_summary(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user),
):
    user_id = str(current_user["_id"])
    summary = await claim_matrix_service.get_project_claim_matrix_summary(
        project_id=project_id, 
        user_id=user_id
    )
    
    return {
        "success": True,
        "data": ClaimMatrixSummary(**summary).model_dump(),
        "message": "Claim matrix summary fetched",
    }
