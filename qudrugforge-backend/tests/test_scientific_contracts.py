import pytest
from datetime import datetime, timezone
from app.schemas.base_result import BaseScientificResult
from app.schemas.docking import DockingResultItem
from app.schemas.admet import AdmetResultResponse
from app.schemas.quantum import QuantumResultItem
from app.schemas.gnina import GninaResultItem
from app.schemas.simulation import SimulationResultResponse
from app.schemas.report import ReportResponse

def test_base_inheritance():
    """Verify all scientific results inherit from BaseScientificResult."""
    assert issubclass(DockingResultItem, BaseScientificResult)
    assert issubclass(AdmetResultResponse, BaseScientificResult)
    assert issubclass(QuantumResultItem, BaseScientificResult)
    assert issubclass(GninaResultItem, BaseScientificResult)
    assert issubclass(SimulationResultResponse, BaseScientificResult)
    assert issubclass(ReportResponse, BaseScientificResult)

def test_mandatory_fields_and_schema_version():
    """Verify serialization of mandatory fields and default schema_version."""
    now = datetime.now(timezone.utc)
    docking_data = {
        "_id": "603d2b2f8f1b2c3d4e5f6g7h",
        "project_id": "proj-123",
        "workspace_id": "workspace-123",
        "source": "live_compute",
        "experiment_id": "exp-docking-1",
        "pipeline_stage": "docking",
        "engine": "vina",
        "created_at": now,
        "updated_at": now,
        "provenance": {
            "source": "backend-mnl",
            "evidence_status": "live"
        }
    }
    
    response = DockingResultItem.from_mongo(docking_data)
    
    assert response.schema_version == "1.0"
    assert response.source == "live_compute"
    assert response.experiment_id == "exp-docking-1"
    assert response.pipeline_stage == "docking"
    assert response.engine == "vina"
    assert response.provenance.source == "backend-mnl"
    
def test_provenance_vs_confidence():
    """Verify distinction between provenance and scientific confidence."""
    now = datetime.now(timezone.utc)
    admet_data = {
        "_id": "admet-123",
        "project_id": "proj-123",
        "workspace_id": "workspace-123",
        "source": "simulated",
        "experiment_id": "exp-admet-1",
        "pipeline_stage": "admet",
        "engine": "tox21",
        "created_at": now,
        "updated_at": now,
        "provenance": {
            "source": "simulated",
            "evidence_status": "placeholder"
        },
        "confidence_score": 0.95,
        "applicability_domain": {"in_domain": True}
    }
    
    response = AdmetResultResponse.from_mongo(admet_data)
    
    # High confidence does not imply biological validity (provenance evidence_status might be placeholder)
    assert response.confidence_score == 0.95
    assert response.provenance.evidence_status == "placeholder"
    assert response.applicability_domain["in_domain"] is True
    
def test_staleness_and_artifact_linkage():
    """Verify artifact linkage and aging/staleness serialization."""
    now = datetime.now(timezone.utc)
    report_data = {
        "report_id": "report-999",
        "workspace_id": "workspace-123",
        "project_id": "proj-123",
        "title": "Final Dossier",
        "report_type": "candidate_dossier",
        "source_module": "reports",
        "source": "imported",
        "experiment_id": "exp-report-1",
        "pipeline_stage": "reporting",
        "engine": "qudrugforge-reports",
        "created_at": now,
        "updated_at": now,
        "provenance": {
            "source": "manual_import",
            "evidence_status": "live"
        },
        "artifact_id": "file-777",
        "artifact_uri": "/api/v1/files/file-777",
        "imported_at": now,
        "stale": True,
        "partial_result": True
    }
    
    response = ReportResponse.from_mongo(report_data)
    
    assert response.artifact_id == "file-777"
    assert response.artifact_uri == "/api/v1/files/file-777"
    assert response.stale is True
    assert response.partial_result is True
    assert response.source == "imported"
