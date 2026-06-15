import pytest
from unittest.mock import patch

@pytest.mark.asyncio
@patch("app.repositories.pipeline_repository.PipelineRepository.collection.count_documents")
async def test_queue_quota_exceeded(mock_count, async_client, auth_token):
    """
    Test Phase 7B Queue Quota:
    If a user has 2 or more active pipelines, they should receive a 429 Too Many Requests.
    """
    mock_count.return_value = 2  # Matches MAX_ACTIVE_JOBS_PER_USER
    
    headers = {"Authorization": f"Bearer {auth_token}"}
    project_id = "507f1f77bcf86cd799439011"  # Dummy valid ObjectId
    
    # Mock project_repository so authorization passes
    with patch("app.repositories.project_repository.ProjectRepository.get_project_by_id") as mock_proj:
        mock_proj.return_value = {"_id": project_id, "workspace_id": "507f1f77bcf86cd799439012"}
        
        with patch("app.repositories.workspace_repository.WorkspaceRepository.get_membership") as mock_mem:
            mock_mem.return_value = {"role": "admin"}
            
            payload = {
                "pipeline": ["docking"],
                "parameters": {}
            }
            response = await async_client.post(
                f"/api/v1/projects/{project_id}/pipeline/run",
                json=payload,
                headers=headers
            )
            
            assert response.status_code == 429
            data = response.json()
            assert data["code"] == "QUEUE_QUOTA_EXCEEDED"
