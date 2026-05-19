from datetime import datetime, timezone
from pathlib import Path

import pytest
from bson import ObjectId


REPORT_SAMPLE_KEYS = ["molecules", "docking", "gnina", "quantum", "admet", "simulations"]


async def _seed_report_context(test_db, project_id: str, workspace_id: str) -> None:
    now = datetime.now(timezone.utc)
    molecule_id = ObjectId()

    seed_docs = {
        "molecules": [
            {
                "_id": molecule_id,
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "compound_id": "cand_001",
                "smiles": "CCO",
                "status": "candidate",
                "mw": 46.07,
                "logp": -0.1,
                "qed": 0.72,
                "created_at": now,
            }
        ],
        "docking_results": [
            {
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "compound_id": "cand_001",
                "binding_affinity": -8.7,
                "pose_rank": 1,
                "created_at": now,
            }
        ],
        "gnina_results": [
            {
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "compound_id": "cand_001",
                "cnn_affinity": -9.2,
                "cnn_pose_score": 0.91,
                "cnn_vs": 0.88,
                "created_at": now,
            }
        ],
        "quantum_results": [
            {
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "compound_id": "cand_001",
                "qml_score": 0.83,
                "homo_ev": -5.3,
                "lumo_ev": -1.1,
                "gap_ev": 4.2,
                "dipole_debye": 1.7,
                "created_at": now,
            }
        ],
        "admet_results": [
            {
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "compound_id": "cand_001",
                "overall_risk": "low",
                "lipinski_violations": 0,
                "ames_toxicity_risk": "low",
                "herg_risk": "low",
                "hepatotoxicity_risk": "low",
                "admet_recommendation": "Proceed",
                "created_at": now,
            }
        ],
        "simulation_results": [
            {
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "compound_id": "cand_001",
                "stability_score": 0.93,
                "rmsd_avg": 1.2,
                "rmsf_avg": 0.8,
                "created_at": now,
            }
        ],
    }

    for collection_name, docs in seed_docs.items():
        for doc in docs:
            await test_db[collection_name].insert_one(doc)


@pytest.mark.asyncio
async def test_create_project_summary_report(async_client, auth_headers, project):
    payload = {
        "title": "Project Summary Draft",
        "report_type": "project_summary",
    }
    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["status"] == "draft"
    assert report["report_type"] == "project_summary"
    assert report["title"] == "Project Summary Draft"


@pytest.mark.asyncio
async def test_list_reports(async_client, auth_headers, project):
    await async_client.post(
        f"/api/v1/projects/{project['id']}/reports",
        json={"title": "List Me", "report_type": "project_summary"},
        headers=auth_headers,
    )

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/reports",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] >= 1
    assert any(report["title"] == "List Me" for report in data["reports"])


@pytest.mark.asyncio
async def test_report_summary(async_client, auth_headers, project, workspace, test_db):
    await _seed_report_context(test_db, project["id"], workspace["id"])

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/reports/summary",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    summary = response.json()["data"]
    assert summary["project_id"] == project["id"]
    assert summary["available_sections"]["overview"] is True
    assert summary["available_sections"]["candidates"] is True
    assert summary["available_sections"]["docking"] is True
    assert summary["available_sections"]["gnina"] is True
    assert summary["available_sections"]["quantum"] is True
    assert summary["available_sections"]["admet"] is True
    assert summary["available_sections"]["simulations"] is True
    assert summary["available_sections"]["artifacts"] is False


@pytest.mark.asyncio
async def test_queue_generation(async_client, auth_headers, project):
    create_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports",
        json={"title": "Queue Draft", "report_type": "project_summary"},
        headers=auth_headers,
    )
    report_id = create_response.json()["data"]["report_id"]

    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/{report_id}/queue-generation",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "queued"


@pytest.mark.asyncio
async def test_generate_report_files(async_client, auth_headers, project, workspace, test_db, test_settings):
    await _seed_report_context(test_db, project["id"], workspace["id"])

    create_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports",
        json={"title": "Generate Me", "report_type": "project_summary"},
        headers=auth_headers,
    )
    report_id = create_response.json()["data"]["report_id"]

    response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/{report_id}/generate",
        json={
            "formats": ["csv", "html", "pdf"],
            "include_sections": REPORT_SAMPLE_KEYS,
            "top_n": 10,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    generated = response.json()["data"]
    assert generated["report"]["status"] == "completed"
    assert len(generated["generated_files"]) >= 1

    report_doc = await test_db["reports"].find_one({"report_id": report_id})
    assert report_doc is not None
    assert report_doc["file_ids"]

    file_meta = await test_db["files"].find_one({"file_id": report_doc["file_ids"][0]})
    assert file_meta is not None
    local_path = Path(test_settings.LOCAL_STORAGE_ROOT) / file_meta["local_path"]
    assert local_path.exists(), f"Generated report file missing at {local_path}"


@pytest.mark.asyncio
async def test_report_files_endpoint(async_client, auth_headers, project, workspace, test_db):
    await _seed_report_context(test_db, project["id"], workspace["id"])

    create_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports",
        json={"title": "File Endpoint", "report_type": "project_summary"},
        headers=auth_headers,
    )
    report_id = create_response.json()["data"]["report_id"]
    await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/{report_id}/generate",
        json={"formats": ["csv", "html", "pdf"], "include_sections": REPORT_SAMPLE_KEYS, "top_n": 10},
        headers=auth_headers,
    )

    response = await async_client.get(
        f"/api/v1/projects/{project['id']}/reports/{report_id}/files",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    files = response.json()["data"]["files"]
    assert files
    assert all(file_item["download_url"] for file_item in files)


@pytest.mark.asyncio
async def test_download_generated_report_file(async_client, auth_headers, project, workspace, test_db):
    await _seed_report_context(test_db, project["id"], workspace["id"])

    create_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports",
        json={"title": "Download File", "report_type": "project_summary"},
        headers=auth_headers,
    )
    report_id = create_response.json()["data"]["report_id"]
    await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/{report_id}/generate",
        json={"formats": ["csv", "html", "pdf"], "include_sections": REPORT_SAMPLE_KEYS, "top_n": 10},
        headers=auth_headers,
    )

    files_response = await async_client.get(
        f"/api/v1/projects/{project['id']}/reports/{report_id}/files",
        headers=auth_headers,
    )
    files = files_response.json()["data"]["files"]
    pdf_file = next((item for item in files if item["file_type"] == "pdf" or item["filename"].endswith(".pdf")), files[0])

    download_response = await async_client.get(
        f"/api/v1/files/{pdf_file['file_id']}/download",
        headers=auth_headers,
    )
    assert download_response.status_code == 200, download_response.text
    assert download_response.headers["content-type"]
    assert len(download_response.content) > 0


@pytest.mark.asyncio
async def test_import_q_ai_drug_report_artifacts_if_available(
    async_client,
    auth_headers,
    project,
    q_ai_drug_output_root,
):
    sample_dir = Path(q_ai_drug_output_root) / "cancer_proof_v1"
    if not sample_dir.exists():
        pytest.skip(f"q-ai-drug sample run not available at {sample_dir}")

    import_artifacts_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/q-ai-drug/import-artifacts",
        json={"run_name": "cancer_proof_v1", "source_output_dir": str(sample_dir), "experiment_id": None},
        headers=auth_headers,
    )
    assert import_artifacts_response.status_code == 200, import_artifacts_response.text

    report_response = await async_client.post(
        f"/api/v1/projects/{project['id']}/reports/import-q-ai-drug",
        json={"source_output_dir": str(sample_dir), "title": "Imported q-ai-drug Report"},
        headers=auth_headers,
    )
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()["data"]
    assert report["status"] == "imported"
    assert report["report_type"] == "imported_q_ai_drug"
    assert report["source"] == "q_ai_drug"
    assert report["file_ids"]
