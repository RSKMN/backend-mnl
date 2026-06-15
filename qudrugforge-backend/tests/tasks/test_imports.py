import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from app.tasks.imports import _run_import, import_artifacts_task
from bson import ObjectId
from app.repositories.job_repository import job_repository

@pytest.fixture
def sample_import_job(test_app):
    job_doc = {
        "project_id": ObjectId(),
        "task_type": "artifact_import",
        "status": "QUEUED",
        "progress": 0,
    }
    return asyncio.run(job_repository.create_job(job_doc))

def test_run_import_success(sample_import_job):
    job_id = str(sample_import_job["_id"])
    
    with patch("app.tasks.imports.artifact_import_service.import_artifacts", new_callable=AsyncMock) as mock_import:
        mock_import.return_value = {"registered_file_ids": ["mock-file-1"]}
        
        result = asyncio.run(_run_import(
            job_id=job_id,
            project_id=str(sample_import_job["project_id"]),
            user_id=str(ObjectId()),
            run_name="test_run",
            experiment_id=str(ObjectId())
        ))
        
        assert result == {"registered_file_ids": ["mock-file-1"]}
        
        # Verify job state transition
        updated_job = asyncio.run(job_repository.get_job_by_id(job_id))
        assert updated_job["status"] == "COMPLETED"
        assert updated_job["progress"] == 100

def test_run_import_failure(sample_import_job):
    job_id = str(sample_import_job["_id"])
    
    with patch("app.tasks.imports.artifact_import_service.import_artifacts", new_callable=AsyncMock) as mock_import:
        mock_import.side_effect = Exception("Mock import error")
        
        # Mock Celery task for the final attempt (retries >= max_retries)
        from celery.exceptions import Retry
        mock_task = MagicMock()
        mock_task.request.retries = 3
        mock_task.max_retries = 3
        mock_task.retry.side_effect = Retry("Retry triggered")
        
        with pytest.raises(Exception):
            import_artifacts_task.run.__func__(
                mock_task,
                job_id=job_id,
                project_id=str(sample_import_job["project_id"]),
                user_id=str(ObjectId()),
                run_name="test_run",
                experiment_id=str(ObjectId())
            )
        
        # Verify job state transition to FAILED on final attempt
        updated_job = asyncio.run(job_repository.get_job_by_id(job_id))
        assert updated_job["status"] == "FAILED"
        assert updated_job["error_message"] == "Mock import error"

def test_run_import_intermediate_retry(sample_import_job):
    job_id = str(sample_import_job["_id"])
    
    with patch("app.tasks.imports.artifact_import_service.import_artifacts", new_callable=AsyncMock) as mock_import:
        mock_import.side_effect = Exception("Mock import error")
        
        # Mock Celery task for an intermediate attempt (retries < max_retries)
        from celery.exceptions import Retry
        mock_task = MagicMock()
        mock_task.request.retries = 1
        mock_task.max_retries = 3
        mock_task.retry.side_effect = Retry("Retry triggered")
        
        with pytest.raises(Retry):
            import_artifacts_task.run.__func__(
                mock_task,
                job_id=job_id,
                project_id=str(sample_import_job["project_id"]),
                user_id=str(ObjectId()),
                run_name="test_run",
                experiment_id=str(ObjectId())
            )
        
        # Verify job is NOT marked FAILED on intermediate attempt (it should remain IMPORTING)
        updated_job = asyncio.run(job_repository.get_job_by_id(job_id))
        assert updated_job["status"] == "IMPORTING"
        
        # Verify TASK_RETRY event was recorded in job_events
        events = asyncio.run(job_repository.events_collection.find({"job_id": ObjectId(job_id), "event_type": "TASK_RETRY"}).to_list(length=10))
        assert len(events) == 1
        assert events[0]["metadata"]["retry_number"] == 2
        assert events[0]["metadata"]["max_retries"] == 3
        assert events[0]["metadata"]["error_message"] == "Mock import error"
        assert "timestamp" in events[0]["metadata"]
