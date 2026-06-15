import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from app.main import app
from app.core.exceptions import (
    OrchestrationFailure,
    MissingEvidenceError,
    DependencyFailure
)
from app.core.responses import success_response, StandardMetadata, ProvenanceMetadata, OrchestrationMetadata

client = TestClient(app)

# Dummy router for testing normalized endpoints
@app.get("/test-orchestration-failure")
def mock_orchestration_failure():
    raise OrchestrationFailure("Compute engine unreachable.", details={"failed_service": "q-ai-drug"})

@app.get("/test-missing-evidence")
def mock_missing_evidence():
    raise MissingEvidenceError("Artifact not found for this target.")

@app.get("/test-partial-success")
def mock_partial_success():
    meta = StandardMetadata(
        orchestration=OrchestrationMetadata(
            partial_failure=True,
            retry_count=1
        ),
        provenance=ProvenanceMetadata(
            source="backend-mnl",
            evidence_status="verified"
        )
    )
    return success_response(data={"completed_items": 5, "total_items": 10}, message="Partial run completed", metadata=meta)

@app.get("/test-simulated-success")
def mock_simulated_success():
    meta = StandardMetadata(
        provenance=ProvenanceMetadata(
            source="simulated",
            evidence_status="placeholder"
        )
    )
    return success_response(data=[], message="Simulated workflow executed", metadata=meta)

def test_orchestration_failure_envelope():
    response = client.get("/test-orchestration-failure")
    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    data = response.json()
    assert data["success"] is False
    assert "error" in data
    assert data["error"]["code"] == "ORCHESTRATION_FAILURE"
    assert data["error"]["message"] == "Compute engine unreachable."
    assert data["error"]["details"]["failed_service"] == "q-ai-drug"

def test_missing_evidence_envelope():
    response = client.get("/test-missing-evidence")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "MISSING_EVIDENCE"

def test_partial_success_envelope():
    response = client.get("/test-partial-success")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["success"] is True
    assert data["metadata"]["orchestration"]["partial_failure"] is True
    assert data["metadata"]["provenance"]["source"] == "backend-mnl"

def test_simulated_success_envelope():
    response = client.get("/test-simulated-success")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["success"] is True
    assert data["metadata"]["provenance"]["source"] == "simulated"
    assert data["metadata"]["provenance"]["evidence_status"] == "placeholder"

def test_health_check_structure():
    response = client.get("/")
    assert response.status_code == status.HTTP_200_OK
    # Health checks natively return standard json objects.
    data = response.json()
    assert "service" in data
    assert data["status"] == "running"
