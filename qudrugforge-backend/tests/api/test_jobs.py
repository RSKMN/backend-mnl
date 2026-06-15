import pytest
from httpx import AsyncClient
from bson import ObjectId
from app.repositories.job_repository import job_repository
from app.utils.datetime import utc_now

@pytest.fixture
async def sample_job(test_app):
    job_doc = {
        "project_id": ObjectId(),
        "task_type": "pipeline_stage",
        "status": "QUEUED",
        "progress": 0,
        "created_at": utc_now(),
    }
    return await job_repository.create_job(job_doc)

@pytest.fixture
async def sample_job_log(test_app, sample_job):
    log_doc = {
        "job_id": ObjectId(sample_job["_id"]),
        "level": "info",
        "message": "Starting job...",
        "timestamp": utc_now()
    }
    res = await job_repository.logs_collection.insert_one(log_doc)
    return str(res.inserted_id)

@pytest.mark.asyncio
async def test_get_job(async_client: AsyncClient, auth_headers, sample_job):
    job_id = str(sample_job["_id"])
    response = await async_client.get(
        f"/api/v1/jobs/{job_id}",
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == job_id
    assert data["data"]["status"] == "QUEUED"

@pytest.mark.asyncio
async def test_get_job_logs(async_client: AsyncClient, auth_headers, sample_job, sample_job_log):
    job_id = str(sample_job["_id"])
    response = await async_client.get(
        f"/api/v1/jobs/{job_id}/logs",
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["data"]["items"]) == 1
    assert data["data"]["items"][0]["message"] == "Starting job..."

@pytest.mark.asyncio
async def test_cancel_job(async_client: AsyncClient, auth_headers, sample_job):
    job_id = str(sample_job["_id"])
    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/cancel",
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["status"] == "CANCELLED"
    assert data["data"]["error_message"] == "Job was cancelled by user."

@pytest.mark.asyncio
async def test_cancel_completed_job_fails(async_client: AsyncClient, auth_headers, sample_job):
    job_id = str(sample_job["_id"])
    await job_repository.update_job_status(job_id, "COMPLETED")
    
    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/cancel",
        headers=auth_headers
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_JOB_STATE"
