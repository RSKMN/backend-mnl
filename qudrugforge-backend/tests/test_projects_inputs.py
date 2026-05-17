import pytest

@pytest.mark.asyncio
async def test_projects_crud_lifecycle(async_client, auth_headers, workspace):
    # 1. Create a project
    payload = {
        "workspace_id": workspace["id"],
        "name": "EGFR Target Study",
        "description": "Researching EGFR mutations in NSCLC",
        "disease_type": "Cancer",
        "cancer_type": "NSCLC"
    }
    res_create = await async_client.post("/api/v1/projects", json=payload, headers=auth_headers)
    assert res_create.status_code == 200
    project = res_create.json()["data"]
    assert project["name"] == "EGFR Target Study"
    assert project["status"] == "draft"

    # 2. List projects
    res_list = await async_client.get(f"/api/v1/projects?workspace_id={workspace['id']}", headers=auth_headers)
    assert res_list.status_code == 200
    assert len(res_list.json()["data"]["items"]) >= 1

    # 3. Get project detail
    res_detail = await async_client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers)
    assert res_detail.status_code == 200
    assert res_detail.json()["data"]["name"] == "EGFR Target Study"

    # 4. Patch project
    update_payload = {
        "name": "EGFR Hardening Study"
    }
    res_patch = await async_client.patch(f"/api/v1/projects/{project['id']}", json=update_payload, headers=auth_headers)
    assert res_patch.status_code == 200
    assert res_patch.json()["data"]["name"] == "EGFR Hardening Study"

    # 5. Project overview
    res_overview = await async_client.get(f"/api/v1/projects/{project['id']}/overview", headers=auth_headers)
    assert res_overview.status_code == 200
    assert "project" in res_overview.json()["data"]

    # 6. Project timeline
    res_timeline = await async_client.get(f"/api/v1/projects/{project['id']}/timeline", headers=auth_headers)
    assert res_timeline.status_code == 200
    assert "items" in res_timeline.json()["data"]

@pytest.mark.asyncio
async def test_project_inputs_configuration(async_client, auth_headers, project):
    project_id = project["id"]

    # 1. Fetch initial empty project inputs
    res_get = await async_client.get(f"/api/v1/projects/{project_id}/inputs", headers=auth_headers)
    assert res_get.status_code == 200
    inputs = res_get.json()["data"]
    assert inputs["project_id"] == project_id

    # 2. Update disease/target metadata
    update_payload = {
        "disease_type": "Adenocarcinoma",
        "target_gene": "EGFR",
        "uniprot_id": "P00533"
    }
    res_put = await async_client.put(f"/api/v1/projects/{project_id}/inputs", json=update_payload, headers=auth_headers)
    assert res_put.status_code == 200
    assert res_put.json()["data"]["target_gene"] == "EGFR"
    assert res_put.json()["data"]["uniprot_id"] == "P00533"

    # 3. Update binding site box
    box_payload = {
        "mode": "box",
        "box": {
            "center_x": 12.5,
            "center_y": -4.2,
            "center_z": 22.0,
            "size_x": 15.0,
            "size_y": 15.0,
            "size_z": 15.0
        }
    }
    res_box = await async_client.patch(f"/api/v1/projects/{project_id}/inputs/binding-site", json=box_payload, headers=auth_headers)
    assert res_box.status_code == 200
    assert res_box.json()["data"]["binding_site"]["box"]["center_x"] == 12.5

    # 4. Update binding site residues
    residues_payload = {
        "mode": "residues",
        "residues": ["THR790", "MET790", "LEU844"]
    }
    res_res = await async_client.patch(f"/api/v1/projects/{project_id}/inputs/binding-site", json=residues_payload, headers=auth_headers)
    assert res_res.status_code == 200
    assert res_res.json()["data"]["binding_site"]["residues"] == ["THR790", "MET790", "LEU844"]

    # 5. Check input completeness
    res_complete = await async_client.get(f"/api/v1/projects/{project_id}/inputs/completeness", headers=auth_headers)
    assert res_complete.status_code == 200
    assert "overall_ready" in res_complete.json()["data"]
