"""Phase 12 Quantum/QML backend API tests."""

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
    async_client, auth_headers, project_id, uploaded_pdb_file, uploaded_ligands_csv
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


async def _create_gnina_run(
    async_client, auth_headers, project_id, uploaded_pdb_file, uploaded_ligands_csv
):
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
            json={
                "source_docking_experiment_id": docking["experiment_id"],
                "top_n": 10,
                "parameters": {"cnn_scoring": True},
            },
            headers=auth_headers,
        )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _quantum_payload(source_experiment_id, method="qml", top_n=10):
    return {
        "source_experiment_id": source_experiment_id,
        "parameters": {
            "method": method,
            "top_n": top_n,
            "compute_descriptors": True,
            "compute_qml_scores": True,
        },
    }


async def _seed_quantum_result(test_db, project, **overrides):
    now = utc_now()
    doc = {
        "project_id": ObjectId(project["id"]),
        "workspace_id": ObjectId(project["workspace_id"]),
        "experiment_id": ObjectId(),
        "compound_id": "cand_001",
        "smiles": "CCO",
        "qm_descriptors": {
            "homo_ev": -6.1,
            "lumo_ev": -1.2,
            "gap_ev": 4.9,
            "dipole_debye": 1.5,
        },
        "quantum_prefilter_score": 0.75,
        "quantum_kernel_score": 0.81,
        "qml_score": 0.82,
        "quantum_rank": 1,
        "rank": 1,
        "source_file_ids": [],
        "raw": {},
        "metadata": {},
        "status": "imported",
        "created_at": now,
        "updated_at": now,
    }
    doc.update(overrides)
    await test_db["quantum_results"].insert_one(doc)
    return doc


@pytest.mark.asyncio
async def test_quantum_protected_routes_reject_missing_token(async_client, project):
    project_id = project["id"]
    routes = [
        ("post", f"/api/v1/projects/{project_id}/quantum/runs"),
        ("get", f"/api/v1/projects/{project_id}/quantum/descriptors"),
        ("get", f"/api/v1/projects/{project_id}/quantum/qml-scores"),
        ("get", f"/api/v1/projects/{project_id}/quantum/reranking"),
        ("get", f"/api/v1/projects/{project_id}/quantum/prefilter"),
    ]
    for method, url in routes:
        response = await async_client.post(url, json={}) if method == "post" else await async_client.get(url)
        assert response.status_code in (401, 403, 422), response.text


@pytest.mark.asyncio
async def test_quantum_run_with_source_gnina_creates_quantum_experiment(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    gnina = await _create_gnina_run(
        async_client, auth_headers, project["id"], uploaded_pdb_file, uploaded_ligands_csv
    )
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/quantum/runs",
        json=_quantum_payload(gnina["experiment_id"]),
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["source_experiment_type"] == "gnina"

    experiment_response = await async_client.get(
        f"/api/v1/projects/{project['id']}/experiments/{data['experiment_id']}",
        headers=auth_headers,
    )
    assert experiment_response.status_code == 200, experiment_response.text
    experiment = experiment_response.json()["data"]
    assert experiment["type"] == "quantum"
    assert experiment["engine"] == "qml"


@pytest.mark.asyncio
async def test_quantum_run_with_source_docking_creates_quantum_experiment(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    docking = await _create_docking_run(
        async_client, auth_headers, project["id"], uploaded_pdb_file, uploaded_ligands_csv
    )
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/quantum/runs",
        json=_quantum_payload(docking["experiment_id"]),
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["source_experiment_type"] == "docking"

    experiment_response = await async_client.get(
        f"/api/v1/projects/{project['id']}/experiments/{data['experiment_id']}",
        headers=auth_headers,
    )
    assert experiment_response.json()["data"]["type"] == "quantum"


@pytest.mark.asyncio
async def test_quantum_run_rejects_invalid_source_experiment(async_client, auth_headers, project):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/quantum/runs",
        json=_quantum_payload(str(ObjectId())),
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert "SOURCE_EXPERIMENT_NOT_FOUND" in response.text


@pytest.mark.asyncio
async def test_quantum_run_rejects_non_docking_or_gnina_source(async_client, auth_headers, project):
    experiment_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/experiments",
        json={
            "name": "Simulation Run",
            "type": "simulation",
            "engine": "md",
            "parameters": {},
            "input_file_ids": [],
            "simulate": False,
        },
        headers=auth_headers,
    )
    assert experiment_response.status_code == 200, experiment_response.text

    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/quantum/runs",
        json=_quantum_payload(experiment_response.json()["data"]["id"]),
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "SOURCE_EXPERIMENT_INVALID" in response.text


@pytest.mark.asyncio
async def test_quantum_run_rejects_invalid_top_n(async_client, auth_headers, project):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/quantum/runs",
        json=_quantum_payload(str(ObjectId()), top_n=0),
        headers=auth_headers,
    )
    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_quantum_run_rejects_invalid_method(async_client, auth_headers, project):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/quantum/runs",
        json=_quantum_payload(str(ObjectId()), method="alchemy"),
        headers=auth_headers,
    )
    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_quantum_descriptors_route_returns_homo_lumo_gap_fields(
    async_client, auth_headers, project, test_db
):
    await _seed_quantum_result(test_db, project)
    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/quantum/descriptors",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["homo_ev"] == -6.1
    assert item["lumo_ev"] == -1.2
    assert item["gap_ev"] == 4.9


@pytest.mark.asyncio
async def test_quantum_qml_scores_route_returns_qml_and_kernel_fields(
    async_client, auth_headers, project, test_db
):
    await _seed_quantum_result(test_db, project, qml_score=0.91, quantum_kernel_score=0.88)
    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/quantum/qml-scores",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["qml_score"] == 0.91
    assert item["kernel_score"] == 0.88


@pytest.mark.asyncio
async def test_quantum_reranking_route_sorts_by_quantum_rank(
    async_client, auth_headers, project, test_db
):
    await _seed_quantum_result(
        test_db, project, compound_id="cand_002", quantum_rank=2, rank=2, quantum_kernel_score=0.95
    )
    await _seed_quantum_result(
        test_db, project, compound_id="cand_001", quantum_rank=1, rank=1, quantum_kernel_score=0.80
    )
    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/quantum/reranking",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert [item["quantum_rank"] for item in items[:2]] == [1, 2]


@pytest.mark.asyncio
async def test_quantum_prefilter_route_returns_prefilter_score(
    async_client, auth_headers, project, test_db
):
    await _seed_quantum_result(test_db, project, quantum_prefilter_score=0.77)
    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/quantum/prefilter",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["prefilter_score"] == 0.77


@pytest.mark.asyncio
async def test_imported_qm_descriptors_appear_in_quantum_descriptors(
    async_client, auth_headers, project
):
    import_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/q-ai-drug/import-artifacts",
        json={"run_name": "cancer_proof_v1", "source_output_dir": None, "experiment_id": None},
        headers=auth_headers,
    )
    assert import_response.status_code == 200, import_response.text

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/quantum/descriptors",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["homo_ev"] is not None
    assert item["lumo_ev"] is not None
    assert item["gap_ev"] is not None


@pytest.mark.asyncio
async def test_imported_quantum_prefilter_scores_appear_in_prefilter(
    async_client, auth_headers, project
):
    import_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/q-ai-drug/import-artifacts",
        json={"run_name": "cancer_proof_v1", "source_output_dir": None, "experiment_id": None},
        headers=auth_headers,
    )
    assert import_response.status_code == 200, import_response.text

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/quantum/prefilter",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["items"][0]["prefilter_score"] is not None


@pytest.mark.asyncio
async def test_imported_quantum_kernel_scores_appear_in_qml_scores(
    async_client, auth_headers, project
):
    import_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/q-ai-drug/import-artifacts",
        json={"run_name": "cancer_proof_v1", "source_output_dir": None, "experiment_id": None},
        headers=auth_headers,
    )
    assert import_response.status_code == 200, import_response.text

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/quantum/qml-scores",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["kernel_score"] is not None


@pytest.mark.asyncio
async def test_quantum_run_does_not_require_q_ai_drug_compute(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    docking = await _create_docking_run(
        async_client, auth_headers, project["id"], uploaded_pdb_file, uploaded_ligands_csv
    )
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/quantum/runs",
        json=_quantum_payload(docking["experiment_id"]),
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "queued"
