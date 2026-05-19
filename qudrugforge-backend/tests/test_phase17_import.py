import pytest
from pathlib import Path
from bson import ObjectId
from app.services.report_service import report_service
from app.core.exceptions import AppException

@pytest.mark.asyncio
async def test_import_validation_missing_both(async_client, auth_headers, project):
    # Should throw 422 Unprocessable Content because both source_output_dir and file_ids are missing
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/import-q-ai-drug",
        json={"title": "Test Missing Params"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "Either 'source_output_dir' or 'file_ids' must be specified" in response.text

@pytest.mark.asyncio
async def test_import_validation_directory_not_found(async_client, auth_headers, project):
    # Should throw 404 Q_AI_DRUG_OUTPUT_NOT_FOUND since the directory does not exist
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/import-q-ai-drug",
        json={"source_output_dir": "non_existent_run_directory_xyz", "title": "Test Missing Dir"},
        headers=auth_headers,
    )
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "Q_AI_DRUG_OUTPUT_NOT_FOUND"

@pytest.mark.asyncio
async def test_import_validation_no_report_formats_found(async_client, auth_headers, project, q_ai_drug_output_root):
    sample_dir = Path(q_ai_drug_output_root) / "cancer_proof_v1"
    if not sample_dir.exists():
        pytest.skip(f"q-ai-drug sample run not available at {sample_dir}")

    # Don't run artifact importer first (so no files exist in project's metadata).
    # Since no files exist, it should raise 404 NO_REPORT_FILES_FOUND or NO_REPORT_FORMATS_FOUND.
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/import-q-ai-drug",
        json={"source_output_dir": "cancer_proof_v1", "title": "Test Empty Formats"},
        headers=auth_headers,
    )
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] in ["NO_REPORT_FILES_FOUND", "NO_REPORT_FORMATS_FOUND"]

@pytest.mark.asyncio
async def test_import_success_and_deduplication(
    async_client,
    auth_headers,
    project,
    q_ai_drug_output_root,
):
    sample_dir = Path(q_ai_drug_output_root) / "cancer_proof_v1"
    if not sample_dir.exists():
        pytest.skip(f"q-ai-drug sample run not available at {sample_dir}")

    # 1. Run artifact importer first
    import_artifacts_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/q-ai-drug/import-artifacts",
        json={"run_name": "cancer_proof_v1", "source_output_dir": str(sample_dir), "experiment_id": None},
        headers=auth_headers,
    )
    assert import_artifacts_response.status_code == 200

    # 2. Trigger the report import
    report_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/import-q-ai-drug",
        json={"source_output_dir": "cancer_proof_v1", "title": ""}, # Pass empty title for testing fallback
        headers=auth_headers,
    )
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()["data"]
    assert report["status"] == "imported"
    assert report["report_type"] == "imported_q_ai_drug"
    assert report["source"] == "q_ai_drug"
    assert "cancer_proof_v1" in report["title"] # Ensure fallback uses the run name!

    # 3. Call again to verify deduplication guard returns the existing report instead of creating a new one
    dup_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/import-q-ai-drug",
        json={"source_output_dir": "cancer_proof_v1", "title": "A New Title"},
        headers=auth_headers,
    )
    assert dup_response.status_code == 200
    dup_report = dup_response.json()["data"]
    assert dup_report["report_id"] == report["report_id"]
    # The title should remain the original one, not updated by deduplicated call
    assert dup_report["title"] == report["title"]
