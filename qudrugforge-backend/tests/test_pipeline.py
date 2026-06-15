import pytest
import asyncio
from unittest.mock import patch, MagicMock
from bson import ObjectId
from app.repositories.pipeline_repository import pipeline_repository
from app.repositories.experiment_repository import experiment_repository
from app.utils.datetime import utc_now
from app.services.pipeline_orchestrator_service import pipeline_orchestrator_service

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

    from app.repositories.job_repository import job_repository
    from app.utils.datetime import utc_now
    from bson import ObjectId

    bg_tasks = []

    async def mock_dispatch_stage_chain_local(self, stage: str, exp_id: str, project_id: str, user_id: str, params: dict, pipeline_run_id: str) -> str:
        job_doc = {
            "project_id": ObjectId(project_id),
            "experiment_id": ObjectId(exp_id),
            "task_type": f"stage_{stage}",
            "status": "QUEUED",
            "progress": 0,
            "created_at": utc_now()
        }
        job = await job_repository.create_job(job_doc)
        stage_job_id = str(job["_id"])
        
        async def run_chain():
            try:
                await self.execute_engine_stage_sync(stage, exp_id, project_id, user_id, params, pipeline_run_id, stage_job_id)
                from app.tasks.imports import _run_import
                await _run_import(stage_job_id, project_id, user_id, "cancer_proof_v1", exp_id)
            except Exception as exc:
                await job_repository.update_job_status(stage_job_id, "FAILED", error_message=str(exc))

        task = asyncio.create_task(run_chain())
        bg_tasks.append(task)
        return stage_job_id

    def mock_apply_async(args=None, kwargs=None, **etc):
        task = asyncio.create_task(pipeline_orchestrator_service.run_pipeline_supervisor(*args))
        bg_tasks.append(task)
        return MagicMock()

    with patch("app.tasks.pipeline.run_pipeline_task.apply_async", mock_apply_async), \
         patch.object(pipeline_orchestrator_service.__class__, "_dispatch_stage_chain", mock_dispatch_stage_chain_local):

        # Trigger pipeline run POST endpoint
        response = await async_client.post(
            f"/api/v1/projects/{project_id}/pipeline/run",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"].lower() in ("queued", "running")
        
        pipeline_run_id = data["pipeline_run_id"]

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

        # Clean up background tasks
        for task in bg_tasks:
            if not task.done():
                task.cancel()


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

