import pytest
import httpx
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.core.exceptions import AppException
from app.integrations.q_ai_drug_execution import (
    q_ai_drug_execution_service,
    QAiDrugHttpExecutor,
    QAiDrugCommandExecutor,
    QAiDrugExecutorError
)
from app.core.config import settings

@pytest.mark.asyncio
async def test_http_executor_check_availability_online():
    executor = QAiDrugHttpExecutor()
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        is_online = await executor.check_availability()
        assert is_online is True

@pytest.mark.asyncio
async def test_http_executor_check_availability_offline():
    executor = QAiDrugHttpExecutor()
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Connection refused")
        is_online = await executor.check_availability()
        assert is_online is False

@pytest.mark.asyncio
async def test_http_executor_success_normalization():
    executor = QAiDrugHttpExecutor()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "status": "completed",
        "output_dir": "outputs/cancer_proof_v1",
        "artifacts": ["docking/results.csv"],
        "logs": [{"message": "Running grid rescoring..."}, "Stage finished."]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await executor.execute_stage("target_ranking", {})
        assert res["success"] is True
        assert res["stage"] == "target_ranking"
        assert res["status"] == "completed"
        assert "outputs/cancer_proof_v1" in res["output_dir"]
        assert len(res["artifacts_detected"]) == 1
        assert "Stage finished." in res["logs"]

@pytest.mark.asyncio
async def test_http_executor_timeout_retry_handling():
    executor = QAiDrugHttpExecutor()
    # Force minimal backoff wait to keep tests ultra-fast
    executor.max_retries = 2
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_get.side_effect = httpx.TimeoutException("Request timed out")
        
        with pytest.raises(QAiDrugExecutorError) as exc_info:
            await executor.execute_stage("target_ranking", {})
            
        assert "timed out" in str(exc_info.value)
        assert mock_get.call_count == 2
        assert mock_sleep.call_count == 1

@pytest.mark.asyncio
async def test_http_executor_malformed_response_handling():
    executor = QAiDrugHttpExecutor()
    mock_resp = MagicMock(status_code=200)
    # Simulate a non-JSON raw response
    mock_resp.json.side_effect = ValueError("Not JSON")
    mock_resp.text = "Raw debug trace output"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await executor.execute_stage("quantum", {})
        assert res["success"] is True
        assert res["status"] == "completed"
        assert res["output_dir"] is not None

@pytest.mark.asyncio
async def test_command_executor_subprocess_execution():
    executor = QAiDrugCommandExecutor()
    res = await executor.execute_stage("simulation", {})
    assert res["success"] is True
    assert res["stage"] == "simulation"
    assert res["status"] == "completed"
    assert "Q-AI-Drug CLI compiler validation successful." in res["logs"]

@pytest.mark.asyncio
async def test_execution_service_unavailable_throws_in_strict_http():
    with patch.object(settings, "Q_AI_DRUG_EXECUTION_MODE", "http"), \
         patch.object(q_ai_drug_execution_service.http_executor, "check_availability", new_callable=AsyncMock) as mock_avail:
        mock_avail.return_value = False
        
        with pytest.raises(AppException) as exc_info:
            await q_ai_drug_execution_service.execute_stage("admet", {})
            
        assert exc_info.value.code == "Q_AI_DRUG_UNAVAILABLE"
        assert exc_info.value.status_code == 503

@pytest.mark.asyncio
async def test_execution_service_hybrid_fallback_flows():
    # If HTTP check is online but execution fails, hybrid should catch and execute Command
    with patch.object(settings, "Q_AI_DRUG_EXECUTION_MODE", "hybrid"), \
         patch.object(q_ai_drug_execution_service.http_executor, "check_availability", new_callable=AsyncMock) as mock_avail, \
         patch.object(q_ai_drug_execution_service.http_executor, "execute_stage", new_callable=AsyncMock) as mock_http_exec, \
         patch.object(q_ai_drug_execution_service.command_executor, "execute_stage", new_callable=AsyncMock) as mock_cmd_exec:
        
        mock_avail.return_value = True
        mock_http_exec.side_effect = QAiDrugExecutorError("API trigger offline")
        mock_cmd_exec.return_value = {"success": True, "stage": "gnina", "status": "completed", "logs": ["Command run succeeded"]}

        res = await q_ai_drug_execution_service.execute_stage("gnina", {})
        assert res["success"] is True
        assert mock_cmd_exec.call_count == 1
        assert "Command run succeeded" in res["logs"]
