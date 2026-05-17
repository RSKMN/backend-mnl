from fastapi import APIRouter, Depends, Path, Body
from typing import Dict, Any
from app.services.q_ai_drug_service import q_ai_drug_service
from app.schemas.q_ai_drug import QAiDrugHealthResponse, QAiDrugNormalizedResponse
from app.core.dependencies import get_current_active_user

# Create the router
router = APIRouter(tags=["Compute Integrations"])

@router.get("/integrations/q-ai-drug/health", response_model=Dict[str, Any])
async def get_q_ai_drug_health(current_user: dict = Depends(get_current_active_user)):
    """
    Exposes external q-ai-drug compute backend cluster availability state.
    """
    res = await q_ai_drug_service.health()
    return {
        "success": True,
        "data": res,
        "message": "q-ai-drug health fetched"
    }

@router.get("/projects/{project_id}/q-ai-drug/top-candidates", response_model=Dict[str, Any])
async def get_top_candidates(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    normalized = await q_ai_drug_service.get_top_candidates(project_id, user_id)
    return {
        "success": True,
        "data": normalized,
        "message": "q-ai-drug top candidates data fetched"
    }

@router.get("/projects/{project_id}/q-ai-drug/qm-descriptors", response_model=Dict[str, Any])
async def get_qm_descriptors(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    normalized = await q_ai_drug_service.get_qm_descriptors(project_id, user_id)
    return {
        "success": True,
        "data": normalized,
        "message": "q-ai-drug QM descriptors data fetched"
    }

@router.get("/projects/{project_id}/q-ai-drug/qml-scores", response_model=Dict[str, Any])
async def get_qml_scores(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    normalized = await q_ai_drug_service.get_qml_scores(project_id, user_id)
    return {
        "success": True,
        "data": normalized,
        "message": "q-ai-drug QML scores data fetched"
    }

@router.get("/projects/{project_id}/q-ai-drug/gnina-results", response_model=Dict[str, Any])
async def get_gnina_results(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    normalized = await q_ai_drug_service.get_gnina_results(project_id, user_id)
    return {
        "success": True,
        "data": normalized,
        "message": "q-ai-drug GNINA results data fetched"
    }

@router.get("/projects/{project_id}/q-ai-drug/models", response_model=Dict[str, Any])
async def get_models(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    normalized = await q_ai_drug_service.get_models(project_id, user_id)
    return {
        "success": True,
        "data": normalized,
        "message": "q-ai-drug models data fetched"
    }

@router.get("/projects/{project_id}/q-ai-drug/dashboard", response_model=Dict[str, Any])
async def get_q_ai_drug_dashboard(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    normalized = await q_ai_drug_service.get_dashboard(project_id, user_id)
    return {
        "success": True,
        "data": normalized,
        "message": "q-ai-drug dashboard data fetched"
    }

@router.get("/projects/{project_id}/q-ai-drug/research-summary", response_model=Dict[str, Any])
async def get_q_ai_drug_research_summary(
    project_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    normalized = await q_ai_drug_service.get_research_summary(project_id, user_id)
    return {
        "success": True,
        "data": normalized,
        "message": "q-ai-drug research summary data fetched"
    }

@router.post("/projects/{project_id}/q-ai-drug/models/predict", response_model=Dict[str, Any])
async def predict_with_model(
    project_id: str = Path(...),
    payload: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    normalized = await q_ai_drug_service.predict_with_model(project_id, payload, user_id)
    return {
        "success": True,
        "data": normalized,
        "message": "q-ai-drug model prediction fetched"
    }
