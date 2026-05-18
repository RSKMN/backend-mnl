from datetime import timedelta
from pathlib import Path
import shutil

import pytest
from bson import ObjectId

from app.utils.admet_risk import classify_admet_result
from app.utils.datetime import utc_now


ADMET_ALLOWED_MODELS = ["tox21", "clintox", "lipinski", "herg", "ames", "hepatotoxicity", "cyp", "solubility", "permeability"]


async def _create_project(async_client, auth_headers, workspace, name):
    response = await async_client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace["id"],
            "name": name,
            "description": "Phase 13 ADMET test project",
            "disease_type": "Cancer",
            "cancer_type": "NSCLC",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _insert_molecules(test_db, project, *, status="selected"):
    now = utc_now()
    docs = [
        {
            "project_id": ObjectId(project["id"]),
            "workspace_id": ObjectId(project["workspace_id"]),
            "compound_id": f"{status}-001",
            "smiles": "CCO",
            "name": "Seed 1",
            "status": status,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        },
        {
            "project_id": ObjectId(project["id"]),
            "workspace_id": ObjectId(project["workspace_id"]),
            "compound_id": f"{status}-002",
            "smiles": "CCC",
            "name": "Seed 2",
            "status": status,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        },
    ]
    await test_db["molecules"].insert_many(docs)
    return await test_db["molecules"].find({"project_id": ObjectId(project["id"])}).to_list(length=None)


async def _seed_admet_results(test_db, project, rows):
    now = utc_now()
    docs = []
    for index, row in enumerate(rows):
        doc = {
            "project_id": ObjectId(project["id"]),
            "workspace_id": ObjectId(project["workspace_id"]),
            "experiment_id": row.get("experiment_id", ObjectId()),
            "compound_id": row.get("compound_id", f"cand-{index:03d}"),
            "smiles": row.get("smiles", "CCO"),
            "properties": row.get("properties", {}),
            "raw": row.get("raw", {}),
            "metadata": row.get("metadata", {}),
            "status": "imported",
            "created_at": row.get("created_at", now + timedelta(seconds=index)),
            "updated_at": row.get("updated_at", now + timedelta(seconds=index)),
        }
        doc.update(row)
        docs.append(doc)
    await test_db["admet_results"].insert_many(docs)
    return docs


def _admet_run_payload(source_molecule_set, *, molecule_ids=None, models=None, name=None, simulate=False):
    payload = {
        "source_molecule_set": source_molecule_set,
        "molecule_ids": molecule_ids or [],
        "models": models or ADMET_ALLOWED_MODELS,
        "name": name,
        "simulate": simulate,
    }
    return {key: value for key, value in payload.items() if value is not None}


def _assert_risk_flags(item, expected_flag):
    assert expected_flag in item["risk_flags"]
    assert item["badges"]
    assert item["table_row"]["row_class"].startswith("risk-")


def test_admet_risk_classifier_thresholds():
    low = classify_admet_result(
        {
            "compound_id": "cand-low",
            "herg_risk": 0.12,
            "ames_toxicity_risk": 0.11,
            "hepatotoxicity_risk": 0.09,
            "clintox_risk": 0.1,
            "tox21_risk": 0.2,
            "lipinski_violations": 0,
            "solubility_score": 0.33,
            "permeability_score": 0.51,
            "metabolism_score": 0.62,
        }
    )
    medium = classify_admet_result(
        {
            "compound_id": "cand-medium",
            "herg_risk": 0.22,
            "ames_toxicity_risk": 0.44,
            "hepatotoxicity_risk": 0.21,
            "clintox_risk": 0.3,
            "tox21_risk": 0.29,
            "lipinski_violations": 2,
        }
    )
    high = classify_admet_result(
        {
            "compound_id": "cand-high",
            "herg_risk": 0.91,
            "ames_toxicity_risk": 0.16,
            "hepatotoxicity_risk": 0.15,
            "clintox_risk": 0.82,
            "tox21_risk": 0.28,
            "lipinski_violations": 1,
        }
    )

    assert low["overall_risk"] == "low"
    assert medium["overall_risk"] == "medium"
    assert high["overall_risk"] == "high"
    assert low["recommendation"] == "advance"
    assert medium["recommendation"] == "review"
    assert high["recommendation"] == "reject"
    assert set(low["radar"]) == {"toxicity", "drug_likeness", "solubility", "permeability", "metabolism"}


@pytest.mark.asyncio
async def test_admet_routes_require_auth(async_client, project):
    project_id = project["id"]
    fake_exp_id = str(ObjectId())

    routes = [
        ("post", f"/api/v1/projects/{project_id}/admet/runs"),
        ("get", f"/api/v1/projects/{project_id}/admet/results"),
        ("get", f"/api/v1/projects/{project_id}/admet/risk-table"),
        ("get", f"/api/v1/projects/{project_id}/admet/summary"),
    ]
    for method, url in routes:
        response = await async_client.post(url, json={}) if method == "post" else await async_client.get(url)
        assert response.status_code in (401, 403, 422), response.text


@pytest.mark.asyncio
async def test_valid_admet_run_selected_creates_admet_experiment(async_client, auth_headers, project, test_db):
    project_id = project["id"]
    molecules = await _insert_molecules(test_db, project, status="selected")
    molecule_ids = [str(molecules[0]["_id"])]

    response = await async_client.post(
        f"/api/v1/projects/{project_id}/admet/runs",
        json=_admet_run_payload("selected", molecule_ids=molecule_ids),
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["engine"] == "admet"

    experiment_response = await async_client.get(
        f"/api/v1/projects/{project_id}/experiments/{data['experiment_id']}",
        headers=auth_headers,
    )
    assert experiment_response.status_code == 200, experiment_response.text
    experiment = experiment_response.json()["data"]
    assert experiment["type"] == "admet"
    assert experiment["engine"] == "admet"


@pytest.mark.asyncio
async def test_valid_admet_run_filtered_creates_admet_experiment(async_client, auth_headers, project):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/admet/runs",
        json=_admet_run_payload("filtered"),
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["engine"] == "admet"

    experiment_response = await async_client.get(
        f"/api/v1/projects/{project['id']}/experiments/{data['experiment_id']}",
        headers=auth_headers,
    )
    assert experiment_response.status_code == 200, experiment_response.text
    assert experiment_response.json()["data"]["type"] == "admet"


@pytest.mark.asyncio
async def test_selected_mode_with_empty_molecule_ids_rejected(async_client, auth_headers, project):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/admet/runs",
        json=_admet_run_payload("selected", molecule_ids=[]),
        headers=auth_headers,
    )
    assert response.status_code in (400, 422), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_source", ["invalid", "", "dockings"])
async def test_invalid_source_molecule_set_rejected(async_client, auth_headers, project, bad_source):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/admet/runs",
        json=_admet_run_payload(bad_source),
        headers=auth_headers,
    )
    assert response.status_code in (400, 422), response.text


@pytest.mark.asyncio
async def test_invalid_models_rejected(async_client, auth_headers, project):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/admet/runs",
        json=_admet_run_payload("filtered", models=["not-a-model"]),
        headers=auth_headers,
    )
    assert response.status_code in (400, 422), response.text


@pytest.mark.asyncio
async def test_molecule_ids_from_another_project_rejected(async_client, auth_headers, project, workspace, test_db):
    other_project = await _create_project(async_client, auth_headers, workspace, "Other ADMET Project")
    other_molecules = await _insert_molecules(test_db, other_project, status="selected")

    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/admet/runs",
        json=_admet_run_payload("selected", molecule_ids=[str(other_molecules[0]["_id"])]),
        headers=auth_headers,
    )
    assert response.status_code == 403, response.text
    assert "MOLECULE_ACCESS_DENIED" in response.text or "access" in response.text.lower()


@pytest.mark.asyncio
async def test_admet_results_route_returns_admet_records(async_client, auth_headers, project, test_db):
    experiment_id = ObjectId()
    await _seed_admet_results(
        test_db,
        project,
        [
            {
                "experiment_id": experiment_id,
                "compound_id": "cand-low",
                "herg_risk": 0.12,
                "ames_toxicity_risk": 0.11,
                "hepatotoxicity_risk": 0.09,
                "clintox_risk": 0.1,
                "tox21_risk": 0.2,
                "lipinski_violations": 0,
            }
        ],
    )

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/admet/results",
        params={"experiment_id": str(experiment_id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["compound_id"] == "cand-low"
    assert data["items"][0]["overall_risk"] == "low"


@pytest.mark.asyncio
async def test_admet_risk_table_route_returns_badges_and_rows(async_client, auth_headers, project, test_db):
    experiment_id = ObjectId()
    await _seed_admet_results(
        test_db,
        project,
        [
            {
                "experiment_id": experiment_id,
                "compound_id": "cand-medium",
                "herg_risk": 0.22,
                "ames_toxicity_risk": 0.44,
                "hepatotoxicity_risk": 0.21,
                "clintox_risk": 0.3,
                "tox21_risk": 0.29,
                "lipinski_violations": 2,
            }
        ],
    )

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/admet/risk-table",
        params={"experiment_id": str(experiment_id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["badges"]
    assert item["table_row"]["row_class"].startswith("risk-")
    assert item["risk_flags"]


@pytest.mark.asyncio
async def test_admet_summary_route_returns_risk_counts(async_client, auth_headers, project, test_db):
    experiment_id = ObjectId()
    await _seed_admet_results(
        test_db,
        project,
        [
            {
                "experiment_id": experiment_id,
                "compound_id": "cand-low",
                "herg_risk": 0.12,
                "ames_toxicity_risk": 0.11,
                "hepatotoxicity_risk": 0.09,
                "clintox_risk": 0.1,
                "tox21_risk": 0.2,
                "lipinski_violations": 0,
            },
            {
                "experiment_id": experiment_id,
                "compound_id": "cand-medium",
                "herg_risk": 0.22,
                "ames_toxicity_risk": 0.44,
                "hepatotoxicity_risk": 0.21,
                "clintox_risk": 0.3,
                "tox21_risk": 0.29,
                "lipinski_violations": 2,
            },
            {
                "experiment_id": experiment_id,
                "compound_id": "cand-high",
                "herg_risk": 0.91,
                "ames_toxicity_risk": 0.16,
                "hepatotoxicity_risk": 0.15,
                "clintox_risk": 0.82,
                "tox21_risk": 0.28,
                "lipinski_violations": 1,
            },
        ],
    )

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/admet/summary",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total_molecules"] == 3
    assert data["risk_counts"] == {"low": 1, "medium": 1, "high": 1, "unknown": 0}
    assert data["recommendation_counts"] == {"advance": 1, "review": 1, "reject": 1}
    assert set(data["average_scores"]) >= {"overall_risk_score", "toxicity", "drug_likeness", "solubility", "permeability", "metabolism"}
    assert data["top_warnings"]


@pytest.mark.asyncio
async def test_imported_admet_columns_appear_in_results(async_client, auth_headers, project):
    import_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/q-ai-drug/import-artifacts",
        json={"run_name": "cancer_proof_v1", "source_output_dir": None, "experiment_id": None},
        headers=auth_headers,
    )
    assert import_response.status_code == 200, import_response.text
    experiment_id = import_response.json()["data"]["experiment_id"]

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/admet/results",
        params={"experiment_id": experiment_id},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] >= 1
    assert any(item["raw"].get("admet_risk_score") is not None for item in data["items"])
    assert any(item["badges"] for item in data["items"])


@pytest.mark.asyncio
async def test_importer_skips_cleanly_if_no_admet_columns_exist(async_client, auth_headers, project, q_ai_drug_output_root):
    run_dir = Path(q_ai_drug_output_root) / "phase13_no_admet_run"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "generated.csv").write_text(
        "compound_id,canonical_smiles,qed\n"
        "cand_001,c1ccccc1,0.84\n"
        "cand_002,CCO,0.52\n",
        encoding="utf-8",
    )
    (run_dir / "filtered.csv").write_text(
        "compound_id,canonical_smiles,qed\n"
        "cand_001,c1ccccc1,0.84\n"
        "cand_002,CCO,0.52\n",
        encoding="utf-8",
    )

    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/q-ai-drug/import-artifacts",
        json={"run_name": "phase13_no_admet_run", "source_output_dir": None, "experiment_id": None},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["parsed_collections"]["admet_results"] == 0
    assert any("skipped ADMET result import" in warning.lower() or "ADMET" in warning for warning in data["warnings"])

    shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_existing_artifact_import_and_backend_routes_still_pass(async_client, auth_headers, project):
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/q-ai-drug/import-artifacts",
        json={"run_name": "cancer_proof_v1", "source_output_dir": None, "experiment_id": None},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    docking = await async_client.get(f"/api/v1/projects/{project['id']}/docking/results", headers=auth_headers)
    gnina = await async_client.get(f"/api/v1/projects/{project['id']}/gnina/results", headers=auth_headers)
    quantum = await async_client.get(f"/api/v1/projects/{project['id']}/quantum/descriptors", headers=auth_headers)
    artifact = await async_client.get(f"/api/v1/projects/{project['id']}/reports", headers=auth_headers)

    assert docking.status_code == 200
    assert gnina.status_code == 200
    assert quantum.status_code == 200
    assert artifact.status_code == 200