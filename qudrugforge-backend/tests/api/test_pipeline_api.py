import pytest
from httpx import AsyncClient
from bson import ObjectId
from unittest.mock import patch, AsyncMock, MagicMock
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository

@pytest.fixture
async def setup_pipeline_mocks(test_app):
    project_id = str(ObjectId())
    workspace_id = str(ObjectId())
    user_id = str(ObjectId())
    
    await project_repository.collection.insert_one({
        "_id": ObjectId(project_id),
        "workspace_id": ObjectId(workspace_id),
        "name": "Test Project"
    })
    
    await workspace_repository.workspaces_collection.insert_one({
        "_id": ObjectId(workspace_id),
        "name": "Test Workspace",
    })
    
    await workspace_repository.members_collection.insert_one({
        "workspace_id": ObjectId(workspace_id),
        "user_id": ObjectId(user_id),
        "role": "admin",
        "status": "active"
    })
    
    return project_id, workspace_id, user_id

@pytest.mark.asyncio
async def test_trigger_pipeline_run_celery(async_client: AsyncClient, auth_headers, setup_pipeline_mocks):
    project_id, workspace_id, user_id = setup_pipeline_mocks
    
    with patch("app.api.v1.pipeline.check_project_and_authorize", new_callable=AsyncMock) as mock_auth, \
         patch("app.tasks.pipeline.run_pipeline_task.apply_async") as mock_apply:
        
        # Bypass auth for test user mismatch mapping
        mock_auth.return_value = ({"_id": ObjectId(project_id), "workspace_id": ObjectId(workspace_id)}, workspace_id)
        
        response = await async_client.post(
            f"/api/v1/projects/{project_id}/pipeline/run",
            json={
                "pipeline": ["target_ranking"],
                "parameters": {}
            },
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "job_id" in data["data"]
        assert data["data"]["status"] == "QUEUED"
        
        # Verify celery task was dispatched
        assert mock_apply.called
        args, kwargs = mock_apply.call_args
        assert kwargs["queue"] == "pipeline"
        assert len(kwargs["args"]) == 4  # pipeline_run_id, project_id, user_id, supervisor_job_id
