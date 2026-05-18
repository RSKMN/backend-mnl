import pytest
from bson import ObjectId

@pytest.mark.asyncio
async def test_artifact_import_and_results_query(async_client, auth_headers, project, test_db):
    project_id = project["id"]

    # 1. Trigger the artifact import
    import_payload = {
        "run_name": "cancer_proof_v1",
        "source_output_dir": None,
        "experiment_id": None
    }
    res_import = await async_client.post(
        f"/api/v1/projects/{project_id}/q-ai-drug/import-artifacts",
        json=import_payload,
        headers=auth_headers
    )
    assert res_import.status_code == 200
    summary = res_import.json()["data"]
    assert "import_id" in summary
    assert "imported_files" in summary
    assert len(summary["imported_files"]) >= 5
    assert summary["parsed_collections"]["docking_results"] >= 2
    assert summary["parsed_collections"]["gnina_results"] >= 2

    # 2. Query docking results
    res_docking = await async_client.get(
        f"/api/v1/projects/{project_id}/docking/results",
        headers=auth_headers
    )
    assert res_docking.status_code == 200
    assert res_docking.json()["data"]["total"] >= 2
    assert res_docking.json()["data"]["items"][0]["compound_id"] in ["cand_005", "cand_001", "cand_002", "cand_003"]

    # 3. Query gnina results
    res_gnina = await async_client.get(
        f"/api/v1/projects/{project_id}/gnina/results",
        headers=auth_headers
    )
    assert res_gnina.status_code == 200
    gnina_data = res_gnina.json()["data"]
    assert gnina_data["total"] >= 2
    first_gnina = gnina_data["items"][0]
    assert first_gnina["raw"]
    assert "gnina_cnn_score" in first_gnina["raw"]
    assert first_gnina["cnn_pose_score"] is not None
    assert first_gnina["cnn_affinity"] is not None

    registered_pose = await test_db["files"].find_one({
        "project_id": ObjectId(project_id),
        "source_module": "gnina",
        "file_type": "gnina_pose",
    })
    assert registered_pose is not None
    assert registered_pose["metadata"]["relative_source_path"].startswith("gnina/poses/")

    # 4. Query quantum results
    res_quantum = await async_client.get(
        f"/api/v1/projects/{project_id}/quantum/results",
        headers=auth_headers
    )
    assert res_quantum.status_code == 200
    quantum_data = res_quantum.json()["data"]
    assert quantum_data["total"] >= 2
    first_quantum = quantum_data["items"][0]
    assert "homo_ev" in first_quantum["qm_descriptors"]
    assert "lumo_ev" in first_quantum["qm_descriptors"]
    assert "gap_ev" in first_quantum["qm_descriptors"]
    assert "dipole_debye" in first_quantum["qm_descriptors"]
    assert first_quantum["quantum_prefilter_score"] is not None
    assert first_quantum["quantum_kernel_score"] is not None
    assert first_quantum["raw"]["qm_descriptors"]
    assert first_quantum["raw"]["quantum_prefilter"]
    assert first_quantum["raw"]["quantum_kernel"]

    # 5. Query simulation results
    res_sim = await async_client.get(
        f"/api/v1/projects/{project_id}/simulations/results",
        headers=auth_headers
    )
    assert res_sim.status_code == 200
    assert res_sim.json()["data"]["total"] >= 2

    # 6. Query ADMET results (since there was no admet results file, parsed count is 0 or verified)
    res_admet = await async_client.get(
        f"/api/v1/projects/{project_id}/admet/results",
        headers=auth_headers
    )
    assert res_admet.status_code == 200
    admet_data = res_admet.json()["data"]
    assert admet_data["total"] >= 1
    assert admet_data["items"][0]["overall_risk"] in {"low", "medium", "high"}
    assert admet_data["items"][0]["badges"]

    res_admet_summary = await async_client.get(
        f"/api/v1/projects/{project_id}/admet/summary",
        headers=auth_headers
    )
    assert res_admet_summary.status_code == 200
    admet_summary = res_admet_summary.json()["data"]
    assert admet_summary["total_molecules"] >= 1
    assert admet_summary["risk_counts"]["low"] + admet_summary["risk_counts"]["medium"] + admet_summary["risk_counts"]["high"] >= 1

    # 7. Query reports list
    res_reports = await async_client.get(
        f"/api/v1/projects/{project_id}/reports",
        headers=auth_headers
    )
    assert res_reports.status_code == 200
    assert res_reports.json()["data"]["total"] >= 1
