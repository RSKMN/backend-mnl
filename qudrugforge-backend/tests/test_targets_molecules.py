import pytest

@pytest.mark.asyncio
async def test_targets_api_endpoints(async_client, auth_headers, project, uploaded_pdb_file):
    project_id = project["id"]

    # 1. Create a target
    payload = {
        "gene": "EGFR",
        "uniprot_id": "P00533",
        "protein_name": "Epidermal growth factor receptor",
        "structure_file_id": uploaded_pdb_file["file_id"],
        "rank_score": 0.85,
        "status": "candidate",
        "metadata": {"mutations": ["L858R", "T790M"]}
    }
    res_create = await async_client.post(
        f"/api/v1/projects/{project_id}/targets",
        json=payload,
        headers=auth_headers
    )
    assert res_create.status_code == 200
    target = res_create.json()["data"]
    assert target["gene"] == "EGFR"
    assert target["rank_score"] == 0.85

    # 2. List targets
    res_list = await async_client.get(
        f"/api/v1/projects/{project_id}/targets",
        headers=auth_headers
    )
    assert res_list.status_code == 200
    assert len(res_list.json()["data"]["items"]) >= 1

    # 3. Get target details
    res_detail = await async_client.get(
        f"/api/v1/projects/{project_id}/targets/{target['id']}",
        headers=auth_headers
    )
    assert res_detail.status_code == 200
    assert res_detail.json()["data"]["gene"] == "EGFR"

    # 4. Rank targets
    rank_payload = {
        "target_ids": [target["id"]],
        "strategy": "manual"
    }
    res_rank = await async_client.post(
        f"/api/v1/projects/{project_id}/targets/rank",
        json=rank_payload,
        headers=auth_headers
    )
    assert res_rank.status_code == 200
    assert len(res_rank.json()["data"]["items"]) >= 1

@pytest.mark.asyncio
async def test_molecules_api_endpoints(async_client, auth_headers, project, uploaded_ligands_csv):
    project_id = project["id"]
    file_id = uploaded_ligands_csv["file_id"]

    # 1. Import molecules from uploaded CSV library
    import_payload = {
        "source_file_id": file_id,
        "smiles_column": "canonical_smiles",
        "compound_id_column": "compound_id"
    }
    res_import = await async_client.post(
        f"/api/v1/projects/{project_id}/molecules/import",
        json=import_payload,
        headers=auth_headers
    )
    assert res_import.status_code == 200
    summary = res_import.json()["data"]
    assert summary["created_count"] == 5
    assert len(summary["items"]) == 5

    molecule_id = summary["items"][0]["id"]

    # 2. List molecules
    res_list = await async_client.get(
        f"/api/v1/projects/{project_id}/molecules",
        headers=auth_headers
    )
    assert res_list.status_code == 200
    assert res_list.json()["data"]["total"] == 5

    # 3. Get molecule detail
    res_detail = await async_client.get(
        f"/api/v1/projects/{project_id}/molecules/{molecule_id}",
        headers=auth_headers
    )
    assert res_detail.status_code == 200
    assert res_detail.json()["data"]["smiles"] is not None

    # 4. Filter molecules endpoint
    filter_payload = {
        "qed_min": 0.60
    }
    res_filter = await async_client.post(
        f"/api/v1/projects/{project_id}/molecules/filter",
        json=filter_payload,
        headers=auth_headers
    )
    assert res_filter.status_code == 200
    # At least cand_001 (0.85), cand_002 (0.64), cand_005 (0.76) should match
    assert len(res_filter.json()["data"]["items"]) >= 3

    # 5. Generate molecules placeholder
    generate_payload = {
        "count": 5
    }
    res_gen = await async_client.post(
        f"/api/v1/projects/{project_id}/molecules/generate",
        json=generate_payload,
        headers=auth_headers
    )
    assert res_gen.status_code == 200
    assert "will be connected to q-ai-drug" in res_gen.json()["message"]
