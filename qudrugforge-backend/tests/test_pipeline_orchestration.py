import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from bson import ObjectId
from app.services.pipeline_orchestrator_service import pipeline_orchestrator_service
from app.repositories.pipeline_repository import pipeline_repository
from app.repositories.experiment_repository import experiment_repository
from app.repositories.project_repository import project_repository
from app.utils.datetime import utc_now

@pytest.mark.asyncio
async def test_full_pipeline_orchestration_lifecycle(test_db, project, registered_user):
    project_id = project["id"]
    workspace_id = project["workspace_id"]
    user_id = registered_user["user"]["id"]

    # 1. Create a pipeline run enqueuing target stages
    pipeline_run = await pipeline_orchestrator_service.create_pipeline_run(
        project_id=project_id,
        workspace_id=workspace_id,
        pipeline=["docking", "gnina", "report"],
        parameters={},
        user_id=user_id
    )
    pipeline_run_id = str(pipeline_run["_id"])
    assert pipeline_run["status"] == "queued"
    assert len(pipeline_run["pipeline"]) == 3

    # 2. Trigger asynchronous background run
    await pipeline_orchestrator_service.run_pipeline(
        pipeline_run_id=pipeline_run_id,
        project_id=project_id,
        user_id=user_id
    )

    # 3. Fetch completed pipeline run details from database
    final_run = await pipeline_repository.get_pipeline_run_by_id(pipeline_run_id)
    assert final_run is not None
    assert final_run["status"] == "completed"

    # 4. Check that project timestamps were updated correctly
    updated_project = await project_repository.get_project_by_id(project_id)
    assert updated_project.get("last_pipeline_run_at") is not None
    assert updated_project.get("last_results_import_at") is not None

    # 5. Check stage progression and experiment linkage
    stage_statuses = final_run["stage_statuses"]
    assert "docking" in stage_statuses
    assert "gnina" in stage_statuses
    assert "report" in stage_statuses

    docking_exp_id = stage_statuses["docking"]["experiment_id"]
    gnina_exp_id = stage_statuses["gnina"]["experiment_id"]
    report_exp_id = stage_statuses["report"]["experiment_id"]

    assert docking_exp_id is not None
    assert gnina_exp_id is not None
    assert report_exp_id is not None

    # Verify stage experiments link correctly to parent pipeline
    docking_exp = await experiment_repository.get_experiment_by_id(docking_exp_id)
    assert docking_exp is not None
    assert str(docking_exp["parent_pipeline_run_id"]) == pipeline_run_id
    assert docking_exp["status"] in ("completed", "imported")

@pytest.mark.asyncio
async def test_pipeline_execution_failure_handling(test_db, project, registered_user):
    project_id = project["id"]
    workspace_id = project["workspace_id"]
    user_id = registered_user["user"]["id"]

    # 1. Assert invalid pipeline stage triggers validation failure instantly
    with pytest.raises(Exception) as exc_info:
        await pipeline_orchestrator_service.create_pipeline_run(
            project_id=project_id,
            workspace_id=workspace_id,
            pipeline=["docking", "invalid_faulty_stage"],
            parameters={},
            user_id=user_id
        )
    assert "is not recognized or supported" in str(exc_info.value)

    # 2. Mock execute_stage to raise exception and assert run is marked as failed
    pipeline_run = await pipeline_orchestrator_service.create_pipeline_run(
        project_id=project_id,
        workspace_id=workspace_id,
        pipeline=["docking"],
        parameters={},
        user_id=user_id
    )
    pipeline_run_id = str(pipeline_run["_id"])

    # Patch execution adapter to mock execution failure
    with patch("app.integrations.q_ai_drug_execution.q_ai_drug_execution_service.execute_stage", new_callable=AsyncMock) as mock_exec:
        mock_exec.side_effect = Exception("Subprocess adapter simulation failure")

        await pipeline_orchestrator_service.run_pipeline(
            pipeline_run_id=pipeline_run_id,
            project_id=project_id,
            user_id=user_id
        )

    final_run = await pipeline_repository.get_pipeline_run_by_id(pipeline_run_id)
    assert final_run["status"] == "failed"
    assert final_run["stage_statuses"]["docking"]["status"] == "failed"
