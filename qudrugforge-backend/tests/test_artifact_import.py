import pytest

@pytest.mark.asyncio
async def test_artifact_import_and_results_query(async_client, auth_headers, project):
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
    assert res_gnina.json()["data"]["total"] >= 2

    # 4. Query quantum results
    res_quantum = await async_client.get(
        f"/api/v1/projects/{project_id}/quantum/results",
        headers=auth_headers
    )
    assert res_quantum.status_code == 200
    assert res_quantum.json()["data"]["total"] >= 2

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

    # 7. Query reports list
    res_reports = await async_client.get(
        f"/api/v1/projects/{project_id}/reports",
        headers=auth_headers
    )
    assert res_reports.status_code == 200
    assert res_reports.json()["data"]["total"] >= 1
