import pytest
import asyncio
from bson import ObjectId
from app.repositories.pipeline_repository import pipeline_repository
from app.repositories.experiment_repository import experiment_repository
from app.utils.datetime import utc_now

@pytest.mark.asyncio
async def test_pipeline_routes_require_auth(async_client, project):
    project_id = project["id"]
    routes = [
        ("post", f"/api/v1/projects/{project_id}/pipeline/run"),
        ("get", f"/api/v1/projects/{project_id}/pipeline/runs"),
        ("get", f"/api/v1/projects/{project_id}/pipeline/runs/{str(ObjectId())}"),
    ]
    for method, url in routes:
        response = await async_client.post(url, json={}) if method == "post" else await async_client.get(url)
        assert response.status_code in (401, 403, 422), response.text

@pytest.mark.asyncio
async def test_invalid_pipeline_stage_rejected(async_client, auth_headers, project):
    project_id = project["id"]
    payload = {
        "pipeline": ["molecule_generation", "non_existent_stage_name"],
        "parameters": {}
    }
    response = await async_client.post(
        f"/api/v1/projects/{project_id}/pipeline/run",
        json=payload,
        headers=auth_headers
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "INVALID_PIPELINE_STAGE"

@pytest.mark.asyncio
async def test_successful_pipeline_trigger_and_sequential_run(async_client, auth_headers, project, test_db):
    project_id = project["id"]
    payload = {
        "pipeline": [
            "target_ranking",
            "molecule_generation",
            "filtering",
            "docking",
            "gnina",
            "quantum",
            "admet",
            "simulation",
            "report"
        ],
        "parameters": {}
    }

    # Trigger pipeline run POST endpoint
    response = await async_client.post(
        f"/api/v1/projects/{project_id}/pipeline/run",
        json=payload,
        headers=auth_headers
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] in ("queued", "running")
    assert len(data["pipeline"]) == 9
    assert "target_ranking" in data["stage_statuses"]
    
    pipeline_run_id = data["id"]

    # 1. Fetch runs list GET endpoint
    list_response = await async_client.get(
        f"/api/v1/projects/{project_id}/pipeline/runs",
        headers=auth_headers
    )
    assert list_response.status_code == 200
    list_data = list_response.json()["data"]
    assert list_data["total"] >= 1
    assert list_data["items"][0]["id"] == pipeline_run_id

    # 2. Wait slightly for background sequential execution tasks to run
    # Since stages in PipelineOrchestratorService use asyncio.sleep(0.5) per stage,
    # let's wait a moment for at least the first few stages to start/complete.
    await asyncio.sleep(1.0)

    # 3. Retrieve specific pipeline run detail
    detail_response = await async_client.get(
        f"/api/v1/projects/{project_id}/pipeline/runs/{pipeline_run_id}",
        headers=auth_headers
    )
    assert detail_response.status_code == 200
    run_detail = detail_response.json()["data"]
    
    # Assert stages have been sequentially executed & statuses updated
    assert run_detail["stage_statuses"]["target_ranking"]["status"] in ("completed", "running")
    
    # Assert experiment documents were created for executed stages
    target_ranking_exp_id = run_detail["stage_statuses"]["target_ranking"]["experiment_id"]
    assert target_ranking_exp_id is not None
    
    # Check stage experiment linkage fields in database
    stage_exp = await experiment_repository.get_experiment_by_id(target_ranking_exp_id)
    assert stage_exp is not None
    assert str(stage_exp["parent_pipeline_run_id"]) == pipeline_run_id
    assert "parent_pipeline_run_id" in stage_exp["metadata"]
    assert str(stage_exp["metadata"]["parent_pipeline_run_id"]) == pipeline_run_id


@pytest.mark.asyncio
async def test_pipeline_summary_endpoint(async_client, auth_headers, project):
    project_id = project["id"]
    response = await async_client.get(
        f"/api/v1/projects/{project_id}/pipeline/summary",
        headers=auth_headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    summary = data["data"]
    assert "latest_pipeline_run" in summary
    assert "imported_counts" in summary
    assert "generated_reports" in summary
    assert "q_ai_drug_status" in summary
    assert "molecules" in summary["imported_counts"]
    assert "docking_results" in summary["imported_counts"]
    assert "reports" in summary["imported_counts"]
    assert "project_metadata" in summary
    assert "last_pipeline_run_at" in summary["project_metadata"]
    assert "last_results_import_at" in summary["project_metadata"]

