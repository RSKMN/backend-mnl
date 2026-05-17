import pytest
from unittest.mock import AsyncMock, patch
from app.integrations.q_ai_drug_client import q_ai_drug_client

@pytest.fixture
def mock_q_ai_drug_client():
    with patch("app.integrations.q_ai_drug_client.q_ai_drug_client.health", new_callable=AsyncMock) as m_health, \
         patch("app.integrations.q_ai_drug_client.q_ai_drug_client.get_top_candidates", new_callable=AsyncMock) as m_top, \
         patch("app.integrations.q_ai_drug_client.q_ai_drug_client.get_qm_descriptors", new_callable=AsyncMock) as m_qm, \
         patch("app.integrations.q_ai_drug_client.q_ai_drug_client.get_qml_scores", new_callable=AsyncMock) as m_qml, \
         patch("app.integrations.q_ai_drug_client.q_ai_drug_client.get_gnina_results", new_callable=AsyncMock) as m_gnina, \
         patch("app.integrations.q_ai_drug_client.q_ai_drug_client.get_models", new_callable=AsyncMock) as m_models, \
         patch("app.integrations.q_ai_drug_client.q_ai_drug_client.get_dashboard", new_callable=AsyncMock) as m_dash, \
         patch("app.integrations.q_ai_drug_client.q_ai_drug_client.get_research_summary", new_callable=AsyncMock) as m_sum, \
         patch("app.integrations.q_ai_drug_client.q_ai_drug_client.predict_with_model", new_callable=AsyncMock) as m_pred:
        
        m_health.return_value = {"status": "ok", "version": "1.0.0"}
        m_top.return_value = [{"compound_id": "cand_005", "smiles": "CC(=O)OC1ccccc1C(=O)O", "score": 0.89}]
        m_qm.return_value = [{"compound_id": "cand_005", "homo_ev": -5.9, "lumo_ev": -1.4}]
        m_qml.return_value = [{"compound_id": "cand_005", "quantum_prefilter_score": 0.85}]
        m_gnina.return_value = [{"compound_id": "cand_005", "gnina_cnn_score": 0.92}]
        m_models.return_value = [{"model_name": "qml_regressor_v1", "accuracy": 0.94}]
        m_dash.return_value = {"overall_progress": "completed", "runs": 12}
        m_sum.return_value = {"summary": "EGFR research run was successfully compiled."}
        m_pred.return_value = {"prediction": [0.89]}
        
        yield {
            "health": m_health,
            "top": m_top,
            "qm": m_qm,
            "qml": m_qml,
            "gnina": m_gnina,
            "models": m_models,
            "dash": m_dash,
            "sum": m_sum,
            "pred": m_pred
        }

@pytest.mark.asyncio
async def test_q_ai_drug_health(async_client, auth_headers, mock_q_ai_drug_client):
    res = await async_client.get("/api/v1/integrations/q-ai-drug/health", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["available"] is True
    assert data["health"]["status"] == "ok"

@pytest.mark.asyncio
async def test_q_ai_drug_readonly_endpoints(async_client, auth_headers, project, mock_q_ai_drug_client):
    project_id = project["id"]

    # 1. Top Candidates
    res_top = await async_client.get(f"/api/v1/projects/{project_id}/q-ai-drug/top-candidates", headers=auth_headers)
    assert res_top.status_code == 200
    assert len(res_top.json()["data"]["items"]) == 1
    assert res_top.json()["data"]["items"][0]["compound_id"] == "cand_005"

    # 2. QM Descriptors
    res_qm = await async_client.get(f"/api/v1/projects/{project_id}/q-ai-drug/qm-descriptors", headers=auth_headers)
    assert res_qm.status_code == 200
    assert res_qm.json()["data"]["items"][0]["homo_ev"] == -5.9

    # 3. QML Scores
    res_qml = await async_client.get(f"/api/v1/projects/{project_id}/q-ai-drug/qml-scores", headers=auth_headers)
    assert res_qml.status_code == 200
    assert res_qml.json()["data"]["items"][0]["quantum_prefilter_score"] == 0.85

    # 4. GNINA Results
    res_gnina = await async_client.get(f"/api/v1/projects/{project_id}/q-ai-drug/gnina-results", headers=auth_headers)
    assert res_gnina.status_code == 200
    assert res_gnina.json()["data"]["items"][0]["gnina_cnn_score"] == 0.92

    # 5. Models
    res_models = await async_client.get(f"/api/v1/projects/{project_id}/q-ai-drug/models", headers=auth_headers)
    assert res_models.status_code == 200
    assert res_models.json()["data"]["items"][0]["model_name"] == "qml_regressor_v1"

    # 6. Dashboard
    res_dash = await async_client.get(f"/api/v1/projects/{project_id}/q-ai-drug/dashboard", headers=auth_headers)
    assert res_dash.status_code == 200
    assert res_dash.json()["data"]["raw"]["runs"] == 12

    # 7. Research Summary
    res_sum = await async_client.get(f"/api/v1/projects/{project_id}/q-ai-drug/research-summary", headers=auth_headers)
    assert res_sum.status_code == 200
    assert "EGFR research" in res_sum.json()["data"]["raw"]["summary"]

    # 8. Model Predict
    predict_payload = {"compound_id": "cand_005", "smiles": "CC(=O)OC1ccccc1C(=O)O"}
    res_pred = await async_client.post(
        f"/api/v1/projects/{project_id}/q-ai-drug/models/predict",
        json=predict_payload,
        headers=auth_headers
    )
    assert res_pred.status_code == 200
    assert res_pred.json()["data"]["raw"]["prediction"] == [0.89]
