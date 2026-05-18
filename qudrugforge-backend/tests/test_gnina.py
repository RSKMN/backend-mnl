"""Phase 11 GNINA backend API tests."""

from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId

from app.integrations.q_ai_drug_client import QAiDrugClientError
from app.utils.datetime import utc_now


async def _create_target(async_client, auth_headers, project_id, pdb_file_id):
    response = await async_client.post(
        f"/api/v1/projects/{project_id}/targets",
        json={
            "gene": "EGFR",
            "uniprot_id": "P00533",
            "protein_name": "EGFR",
            "structure_file_id": pdb_file_id,
            "rank_score": 0.9,
            "status": "candidate",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _import_molecules(async_client, auth_headers, project_id, csv_file_id):
    response = await async_client.post(
        f"/api/v1/projects/{project_id}/molecules/import",
        json={
            "source_file_id": csv_file_id,
            "smiles_column": "canonical_smiles",
            "compound_id_column": "compound_id",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _set_binding_site(async_client, auth_headers, project_id):
    response = await async_client.patch(
        f"/api/v1/projects/{project_id}/inputs/binding-site",
        json={
            "mode": "box",
            "box": {
                "center_x": 10,
                "center_y": 10,
                "center_z": 10,
                "size_x": 20,
                "size_y": 20,
                "size_z": 20,
            },
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text


async def _create_docking_run(
    async_client,
    auth_headers,
    project_id,
    uploaded_pdb_file,
    uploaded_ligands_csv,
):
    target = await _create_target(
        async_client, auth_headers, project_id, uploaded_pdb_file["file_id"]
    )
    await _import_molecules(
        async_client, auth_headers, project_id, uploaded_ligands_csv["file_id"]
    )
    await _set_binding_site(async_client, auth_headers, project_id)

    response = await async_client.post(
        f"/api/v1/projects/{project_id}/docking/runs",
        json={
            "target_id": target["id"],
            "compound_selection": {"mode": "all"},
            "engine": "vina",
            "parameters": {"exhaustiveness": 8, "num_modes": 9},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _gnina_payload(source_docking_experiment_id, top_n=10):
    return {
        "source_docking_experiment_id": source_docking_experiment_id,
        "top_n": top_n,
        "parameters": {"cnn_scoring": True, "exhaustiveness": 8},
    }


async def _create_gnina_run(
    async_client,
    auth_headers,
    project_id,
    uploaded_pdb_file,
    uploaded_ligands_csv,
):
    docking = await _create_docking_run(
        async_client,
        auth_headers,
        project_id,
        uploaded_pdb_file,
        uploaded_ligands_csv,
    )
    with patch(
        "app.services.gnina_service.q_ai_drug_client.start_gnina",
        new_callable=AsyncMock,
        side_effect=QAiDrugClientError("Unavailable", status_code=503),
    ):
        response = await async_client.post(
            f"/api/v1/projects/{project_id}/gnina/runs",
            json=_gnina_payload(docking["experiment_id"]),
            headers=auth_headers,
        )
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_gnina_protected_routes_reject_missing_token(async_client, project):
    project_id = project["id"]
    fake_id = str(ObjectId())
    routes = [
        ("post", f"/api/v1/projects/{project_id}/gnina/runs"),
        ("get", f"/api/v1/projects/{project_id}/gnina/status"),
        ("get", f"/api/v1/projects/{project_id}/gnina/logs"),
        ("get", f"/api/v1/projects/{project_id}/gnina/results"),
        ("get", f"/api/v1/projects/{project_id}/gnina/poses/{fake_id}"),
    ]

    for method, url in routes:
        if method == "post":
            response = await async_client.post(url, json={})
        else:
            response = await async_client.get(url)
        assert response.status_code in (401, 403, 422), response.text


@pytest.mark.asyncio
async def test_valid_gnina_run_creates_gnina_experiment(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    project_id = project["id"]
    docking = await _create_docking_run(
        async_client, auth_headers, project_id, uploaded_pdb_file, uploaded_ligands_csv
    )

    with patch(
        "app.services.gnina_service.q_ai_drug_client.start_gnina",
        new_callable=AsyncMock,
        side_effect=QAiDrugClientError("Unavailable", status_code=503),
    ):
        response = await async_client.post(
            f"/api/v1/projects/{project_id}/gnina/runs",
            json=_gnina_payload(docking["experiment_id"]),
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["engine"] == "gnina"

    experiment_response = await async_client.get(
        f"/api/v1/projects/{project_id}/experiments/{data['experiment_id']}",
        headers=auth_headers,
    )
    assert experiment_response.status_code == 200, experiment_response.text
    experiment = experiment_response.json()["data"]
    assert experiment["type"] == "gnina"
    assert experiment["engine"] == "gnina"


@pytest.mark.asyncio
async def test_gnina_run_rejects_invalid_source_docking_experiment(
    async_client, auth_headers, project
):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/gnina/runs",
        json=_gnina_payload(str(ObjectId())),
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert "SOURCE_DOCKING_EXPERIMENT_NOT_FOUND" in response.text


@pytest.mark.asyncio
async def test_gnina_run_rejects_non_docking_source(
    async_client, auth_headers, project
):
    project_id = project["id"]
    experiment_response = await async_client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "Quantum Run",
            "type": "quantum",
            "engine": "quantum",
            "parameters": {},
            "input_file_ids": [],
            "simulate": False,
        },
        headers=auth_headers,
    )
    assert experiment_response.status_code == 200, experiment_response.text

    response = await async_client.post(
        f"/api/v1/projects/{project_id}/gnina/runs",
        json=_gnina_payload(experiment_response.json()["data"]["id"]),
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "SOURCE_DOCKING_EXPERIMENT_INVALID" in response.text


@pytest.mark.asyncio
async def test_gnina_run_rejects_invalid_top_n(async_client, auth_headers, project):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/gnina/runs",
        json=_gnina_payload(str(ObjectId()), top_n=0),
        headers=auth_headers,
    )

    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_gnina_status_route_returns_local_experiment_status(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    gnina = await _create_gnina_run(
        async_client,
        auth_headers,
        project["id"],
        uploaded_pdb_file,
        uploaded_ligands_csv,
    )

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/gnina/status",
        params={"experiment_id": gnina["experiment_id"]},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["project_id"] == project["id"]
    assert data["experiment_id"] == gnina["experiment_id"]
    assert data["status"] == "queued"
    assert data["progress"] == 0


@pytest.mark.asyncio
async def test_gnina_logs_route_returns_experiment_logs(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    gnina = await _create_gnina_run(
        async_client,
        auth_headers,
        project["id"],
        uploaded_pdb_file,
        uploaded_ligands_csv,
    )

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/gnina/logs",
        params={"experiment_id": gnina["experiment_id"]},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] >= 1
    assert any("GNINA run queued" == item["message"] for item in data["items"])


@pytest.mark.asyncio
async def test_gnina_results_route_returns_gnina_result_records(
    async_client, auth_headers, project, test_db
):
    now = utc_now()
    experiment_id = ObjectId()
    await test_db["gnina_results"].insert_one(
        {
            "project_id": ObjectId(project["id"]),
            "workspace_id": ObjectId(project["workspace_id"]),
            "experiment_id": experiment_id,
            "compound_id": "CAND-G001",
            "smiles": "CCO",
            "cnn_pose_score": 0.92,
            "cnn_affinity": -10.2,
            "rank": 1,
            "status": "imported",
            "source": "q_ai_drug",
            "pose_file_id": None,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        }
    )

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/gnina/results",
        params={"experiment_id": str(experiment_id)},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["compound_id"] == "CAND-G001"
    assert data["items"][0]["cnn_pose_score"] == 0.92


@pytest.mark.asyncio
async def test_gnina_pose_endpoint_resolves_file_metadata_download_url(
    async_client, auth_headers, project, uploaded_pdb_file
):
    file_id = uploaded_pdb_file["file_id"]

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/gnina/poses/{file_id}",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["file_id"] == file_id
    assert data["project_id"] == project["id"]
    assert data["download_url"] == f"http://test/api/v1/files/{file_id}/download"


@pytest.mark.asyncio
async def test_gnina_q_ai_drug_unavailable_handled_cleanly(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    project_id = project["id"]
    docking = await _create_docking_run(
        async_client, auth_headers, project_id, uploaded_pdb_file, uploaded_ligands_csv
    )

    with patch(
        "app.services.gnina_service.q_ai_drug_client.start_gnina",
        new_callable=AsyncMock,
        side_effect=QAiDrugClientError("Not found", status_code=404),
    ):
        response = await async_client.post(
            f"/api/v1/projects/{project_id}/gnina/runs",
            json=_gnina_payload(docking["experiment_id"]),
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["q_ai_drug_job_id"] is None
