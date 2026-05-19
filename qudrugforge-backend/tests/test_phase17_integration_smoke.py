import os
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_full_backend_real_api_smoke_flow(async_client: AsyncClient, test_settings):
    """
    Phase 17.5 — Complete Integration Smoke Test Flow.
    Verifies the end-to-end real-data API contracts in-memory without heavy compute.
    """
    # --- 1. Register/login test user ---
    email = "integration.smoke@example.com"
    password = "SmokePassword123!"
    register_payload = {
        "email": email,
        "password": password,
        "full_name": "Integration Investigator",
        "workspace_name": "Smoke Lab Workspace"
    }
    
    register_res = await async_client.post("/api/v1/auth/register", json=register_payload)
    assert register_res.status_code == 200, f"Register failed: {register_res.text}"
    register_data = register_res.json()["data"]
    token = register_data["access_token"]
    workspace_id = register_data["workspace"]["id"]
    
    auth_headers = {"Authorization": f"Bearer {token}"}
    
    # Verify login endpoint as well
    login_res = await async_client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    })
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    
    # --- 2. Create workspace ---
    # The registration step automatically creates the primary workspace. Let's list it.
    workspaces_res = await async_client.get("/api/v1/workspaces", headers=auth_headers)
    assert workspaces_res.status_code == 200
    workspaces = workspaces_res.json()["data"]
    assert len(workspaces) >= 1
    assert workspaces[0]["id"] == workspace_id
    
    # --- 3. Create project ---
    project_payload = {
        "workspace_id": workspace_id,
        "name": "Integration Smoke Target Discovery",
        "description": "Verification of absolute real-data backend API workflows",
        "disease_type": "Cancer",
        "cancer_type": "Melanoma"
    }
    project_res = await async_client.post("/api/v1/projects", json=project_payload, headers=auth_headers)
    assert project_res.status_code == 200, f"Project creation failed: {project_res.text}"
    project = project_res.json()["data"]
    project_id = project["id"]
    
    # --- 4. Upload a small CSV and PDB structure files ---
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_files", "ligands.csv")
    pdb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_files", "protein.pdb")
    
    # Upload CSV compound library
    with open(csv_path, "rb") as f:
        csv_res = await async_client.post(
            f"/api/v1/projects/{project_id}/files/upload",
            files={"file": ("ligands.csv", f, "text/csv")},
            data={"file_type": "compound_library", "source_module": "project_inputs"},
            headers=auth_headers
        )
    assert csv_res.status_code == 200, csv_res.text
    csv_file = csv_res.json()["data"]["file"]
    
    # Upload PDB target structure
    with open(pdb_path, "rb") as f:
        pdb_res = await async_client.post(
            f"/api/v1/projects/{project_id}/files/upload",
            files={"file": ("protein.pdb", f, "application/octet-stream")},
            data={"file_type": "protein_structure", "source_module": "project_inputs"},
            headers=auth_headers
        )
    assert pdb_res.status_code == 200, pdb_res.text
    pdb_file = pdb_res.json()["data"]["file"]
    
    # --- 5. Assign project inputs ---
    binding_site_payload = {
        "mode": "box",
        "box": {
            "center_x": 12.5,
            "center_y": 15.0,
            "center_z": -5.5,
            "size_x": 18.0,
            "size_y": 18.0,
            "size_z": 18.0
        }
    }
    inputs_res = await async_client.patch(
        f"/api/v1/projects/{project_id}/inputs/binding-site",
        json=binding_site_payload,
        headers=auth_headers
    )
    assert inputs_res.status_code == 200, inputs_res.text
    
    # --- 6. Create/list molecules ---
    import_payload = {
        "source_file_id": csv_file["file_id"],
        "smiles_column": "canonical_smiles",
        "compound_id_column": "compound_id"
    }
    import_res = await async_client.post(
        f"/api/v1/projects/{project_id}/molecules/import",
        json=import_payload,
        headers=auth_headers
    )
    assert import_res.status_code == 200, import_res.text
    assert import_res.json()["data"]["created_count"] == 5
    
    molecules_res = await async_client.get(f"/api/v1/projects/{project_id}/molecules", headers=auth_headers)
    assert molecules_res.status_code == 200
    molecules_data = molecules_res.json()["data"]
    assert molecules_data["total"] == 5
    molecule_id = molecules_data["items"][0]["id"]
    
    # --- 7. Create target ---
    target_payload = {
        "gene": "BRAF",
        "uniprot_id": "P15056",
        "protein_name": "Serine/threonine-protein kinase B-Raf",
        "structure_file_id": pdb_file["file_id"],
        "rank_score": 0.95,
        "status": "candidate",
        "metadata": {"mutations": ["V600E"]}
    }
    target_res = await async_client.post(
        f"/api/v1/projects/{project_id}/targets",
        json=target_payload,
        headers=auth_headers
    )
    assert target_res.status_code == 200, target_res.text
    
    # --- 8. Create experiment record ---
    exp_payload = {
        "name": "BRAF V600E Virtual Screen",
        "type": "docking",
        "engine": "vina",
        "parameters": {"exhaustiveness": 4},
        "input_file_ids": [pdb_file["file_id"]],
        "simulate": True
    }
    exp_res = await async_client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json=exp_payload,
        headers=auth_headers
    )
    assert exp_res.status_code == 200, exp_res.text
    
    # --- 9. Verify result list endpoints return success even if empty ---
    results_endpoints = [
        f"/api/v1/projects/{project_id}/docking/results",
        f"/api/v1/projects/{project_id}/gnina/results",
        f"/api/v1/projects/{project_id}/quantum/descriptors",
        f"/api/v1/projects/{project_id}/admet/results",
        f"/api/v1/projects/{project_id}/simulations/results"
    ]
    for endpoint in results_endpoints:
        res = await async_client.get(endpoint, headers=auth_headers)
        assert res.status_code == 200, f"Result list check failed for {endpoint}: {res.text}"
        
    # --- 10. Verify visualization chemical-space endpoint returns success ---
    cs_res = await async_client.get(f"/api/v1/projects/{project_id}/chemical-space", headers=auth_headers)
    assert cs_res.status_code == 200, cs_res.text
    assert cs_res.json()["data"]["project_id"] == project_id
    
    # --- 11. Verify similarity search returns success if molecules exist ---
    similarity_payload = {
        "query_molecule_id": molecule_id,
        "top_k": 3,
        "min_similarity": 0.0,
        "include_self": True
    }
    similarity_res = await async_client.post(
        f"/api/v1/projects/{project_id}/similarity/search",
        json=similarity_payload,
        headers=auth_headers
    )
    assert similarity_res.status_code == 200, similarity_res.text
    assert len(similarity_res.json()["data"]["results"]) >= 1
    
    # --- 12. Create report draft ---
    report_payload = {
        "title": "BRAF Preclinical Screen Report",
        "report_type": "project_summary"
    }
    report_res = await async_client.post(
        f"/api/v1/projects/{project_id}/reports",
        json=report_payload,
        headers=auth_headers
    )
    assert report_res.status_code == 200, report_res.text
    report_id = report_res.json()["data"]["report_id"]
    
    # --- 13. Generate report CSV/HTML/PDF ---
    generate_payload = {
        "formats": ["csv", "html", "pdf"],
        "include_sections": ["molecules", "docking", "gnina", "quantum", "admet", "simulations"],
        "top_n": 5
    }
    gen_res = await async_client.post(
        f"/api/v1/projects/{project_id}/reports/{report_id}/generate",
        json=generate_payload,
        headers=auth_headers
    )
    assert gen_res.status_code == 200, gen_res.text
    
    # --- 14. Verify generated file metadata exists ---
    files_res = await async_client.get(
        f"/api/v1/projects/{project_id}/reports/{report_id}/files",
        headers=auth_headers
    )
    assert files_res.status_code == 200, files_res.text
    files_list = files_res.json()["data"]["files"]
    assert len(files_list) >= 1
    file_id = files_list[0]["file_id"]
    
    # --- 15. Verify download endpoint returns file content ---
    download_res = await async_client.get(
        f"/api/v1/files/{file_id}/download",
        headers=auth_headers
    )
    assert download_res.status_code == 200, download_res.text
    assert len(download_res.content) > 0
