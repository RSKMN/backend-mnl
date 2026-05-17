import pytest
import asyncio

@pytest.mark.asyncio
async def test_experiment_simulation_flow(async_client, auth_headers, project, uploaded_pdb_file):
    project_id = project["id"]
    file_id = uploaded_pdb_file["file_id"]

    # 1. Create a simulated experiment
    payload = {
        "name": " EGFR Vina Docking Run",
        "type": "docking",
        "engine": "vina",
        "parameters": {"receptor_id": file_id, "box_center": [10.0, 10.0, 10.0]},
        "input_file_ids": [file_id],
        "simulate": True
    }
    
    res_create = await async_client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json=payload,
        headers=auth_headers
    )
    assert res_create.status_code == 200
    exp = res_create.json()["data"]
    assert exp["name"] == " EGFR Vina Docking Run"
    assert exp["type"] == "docking"
    assert exp["engine"] == "vina"
    
    # Since background task is executed concurrently and JOB_SIMULATION_STEP_SECONDS=0,
    # let's wait a tiny fraction of a second for the background task to complete.
    await asyncio.sleep(0.1)

    # 2. Get experiment details and check completed status
    res_detail = await async_client.get(
        f"/api/v1/projects/{project_id}/experiments/{exp['id']}",
        headers=auth_headers
    )
    assert res_detail.status_code == 200
    assert res_detail.json()["data"]["status"] == "completed"
    assert res_detail.json()["data"]["progress"] == 100

    # 3. Check experiment logs
    res_logs = await async_client.get(
        f"/api/v1/projects/{project_id}/experiments/{exp['id']}/logs",
        headers=auth_headers
    )
    assert res_logs.status_code == 200
    assert res_logs.json()["data"]["total"] >= 3
    assert res_logs.json()["data"]["items"][-1]["message"] == "Experiment completed successfully. All poses stored and indexed"

    # 4. Append a new log trace
    log_payload = {
        "level": "warning",
        "message": "Manual post-processing warning annotation",
        "stage": "curation"
    }
    res_log_append = await async_client.post(
        f"/api/v1/projects/{project_id}/experiments/{exp['id']}/logs",
        json=log_payload,
        headers=auth_headers
    )
    assert res_log_append.status_code == 200
    assert res_log_append.json()["data"][-1]["message"] == "Manual post-processing warning annotation"

    # 5. List experiments
    res_list = await async_client.get(
        f"/api/v1/projects/{project_id}/experiments",
        headers=auth_headers
    )
    assert res_list.status_code == 200
    assert res_list.json()["data"]["total"] >= 1

    # 6. Fetch experiments summary dashboard counts
    res_summary = await async_client.get(
        f"/api/v1/projects/{project_id}/experiments/summary",
        headers=auth_headers
    )
    assert res_summary.status_code == 200
    assert res_summary.json()["data"]["completed"] >= 1

@pytest.mark.asyncio
async def test_experiment_cancellation(async_client, auth_headers, project):
    project_id = project["id"]

    # 1. Create a non-simulated experiment (keeps queued/running state or manually managed)
    payload = {
        "name": " EGFR Cancel Target",
        "type": "quantum",
        "engine": "quantum",
        "parameters": {},
        "input_file_ids": [],
        "simulate": False
    }
    res_create = await async_client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json=payload,
        headers=auth_headers
    )
    assert res_create.status_code == 200
    exp = res_create.json()["data"]
    
    # 2. Cancel the experiment
    res_cancel = await async_client.post(
        f"/api/v1/projects/{project_id}/experiments/{exp['id']}/cancel",
        headers=auth_headers
    )
    assert res_cancel.status_code == 200
    assert res_cancel.json()["data"]["status"] == "cancelled"
