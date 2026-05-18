import pytest
from bson import ObjectId
from app.core.database import get_database

@pytest.mark.asyncio
async def test_viewer_endpoints(async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv):
    project_id = project["id"]
    db = get_database()

    # Create a dummy target
    target_id = str(ObjectId())
    await db["targets"].insert_one({
        "_id": ObjectId(target_id),
        "project_id": ObjectId(project_id),
        "gene": "BRCA1",
        "structure_file_id": uploaded_pdb_file["file_id"],
        "status": "candidate",
        "rank_score": 0.9
    })

    # Create a dummy molecule
    mol_id = str(ObjectId())
    await db["molecules"].insert_one({
        "_id": ObjectId(mol_id),
        "project_id": ObjectId(project_id),
        "compound_id": "QDF-9999",
        "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
        "mw": 180.16,
        "logp": 1.2,
        "qed": 0.8,
        "status": "uploaded",
        "source": "manual",
        "metadata": {}
    })

    # Create a dummy docking result with a pose file id
    docking_res_id = str(ObjectId())
    pose_file_uuid = "dummy-pose-file-uuid"
    await db["docking_results"].insert_one({
        "_id": ObjectId(docking_res_id),
        "project_id": ObjectId(project_id),
        "experiment_id": ObjectId(),
        "molecule_id": ObjectId(mol_id),
        "target_id": ObjectId(target_id),
        "compound_id": "QDF-9999",
        "score": -7.2,
        "pose_file_id": pose_file_uuid,
        "pose_filename": "pose_qdf9999.sdf",
        "status": "completed",
        "rank": 1
    })

    # 1. Test GET /viewer/assets
    res_assets = await async_client.get(
        f"/api/v1/projects/{project_id}/viewer/assets",
        headers=auth_headers
    )
    assert res_assets.status_code == 200
    data_assets = res_assets.json()["data"]
    assert data_assets["project_id"] == project_id
    assert len(data_assets["assets"]) >= 3 # pdb, csv and docking pose

    # Check for classifications
    asset_types = [a["asset_type"] for a in data_assets["assets"]]
    assert "protein_structure" in asset_types
    assert "docking_pose" in asset_types

    # 2. Test GET /viewer/protein/{target_id}
    res_protein = await async_client.get(
        f"/api/v1/projects/{project_id}/viewer/protein/{target_id}",
        headers=auth_headers
    )
    assert res_protein.status_code == 200
    data_protein = res_protein.json()["data"]
    assert data_protein["target_id"] == target_id
    assert data_protein["file_id"] == uploaded_pdb_file["file_id"]
    assert data_protein["viewer_format"] == "pdb"

    # 3. Test GET /viewer/ligand/{molecule_id}
    res_ligand = await async_client.get(
        f"/api/v1/projects/{project_id}/viewer/ligand/{mol_id}",
        headers=auth_headers
    )
    assert res_ligand.status_code == 200
    data_ligand = res_ligand.json()["data"]
    assert data_ligand["molecule_id"] == mol_id
    assert data_ligand["smiles"] == "CC(=O)OC1=CC=CC=C1C(=O)O"
    assert data_ligand["viewer_format"] == "smiles"

    # 4. Test GET /viewer/pose/{result_id}
    res_pose = await async_client.get(
        f"/api/v1/projects/{project_id}/viewer/pose/{docking_res_id}",
        headers=auth_headers
    )
    assert res_pose.status_code == 200
    data_pose = res_pose.json()["data"]
    assert data_pose["result_id"] == docking_res_id
    assert data_pose["result_type"] == "docking"
    assert data_pose["pose_file_id"] == pose_file_uuid
    assert data_pose["scores"]["binding_affinity_kcal_mol"] == -7.2

    # 5. Test GET /viewer/interaction-fingerprint/{result_id}
    res_fp = await async_client.get(
        f"/api/v1/projects/{project_id}/viewer/interaction-fingerprint/{docking_res_id}",
        headers=auth_headers
    )
    assert res_fp.status_code == 200
    data_fp = res_fp.json()["data"]
    assert data_fp["result_id"] == docking_res_id
    assert data_fp["available"] is False
    assert "hydrogen_bonds" in data_fp["interaction_fingerprint"]

@pytest.mark.asyncio
async def test_chemical_space_endpoints(async_client, auth_headers, project):
    project_id = project["id"]
    db = get_database()

    # Create dummy molecules
    mol1_id = str(ObjectId())
    mol2_id = str(ObjectId())
    await db["molecules"].insert_many([
        {
            "_id": ObjectId(mol1_id),
            "project_id": ObjectId(project_id),
            "compound_id": "QDF-0001",
            "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
            "mw": 180.16,
            "logp": 1.2,
            "qed": 0.8,
            "status": "uploaded",
            "source": "manual",
            "metadata": {}
        },
        {
            "_id": ObjectId(mol2_id),
            "project_id": ObjectId(project_id),
            "compound_id": "QDF-0002",
            "smiles": "CN1C2CCC1C(C(C2)OC(=O)C3=CC=CC=C3)C(=O)OC",
            "mw": 303.35,
            "logp": 2.3,
            "qed": 0.7,
            "status": "uploaded",
            "source": "manual",
            "metadata": {}
        }
    ])

    # 1. Test GET /chemical-space
    res_cs = await async_client.get(
        f"/api/v1/projects/{project_id}/chemical-space",
        headers=auth_headers
    )
    assert res_cs.status_code == 200
    data_cs = res_cs.json()["data"]
    assert data_cs["project_id"] == project_id
    assert data_cs["method"] == "deterministic_placeholder"
    assert len(data_cs["points"]) == 2
    assert data_cs["points"][0]["compound_id"] in ("QDF-0001", "QDF-0002")

    # 2. Test POST /chemical-space/recompute
    recompute_payload = {
        "method": "deterministic_placeholder",
        "limit": 100,
        "store": True
    }
    res_recompute = await async_client.post(
        f"/api/v1/projects/{project_id}/chemical-space/recompute",
        json=recompute_payload,
        headers=auth_headers
    )
    assert res_recompute.status_code == 200
    data_recompute = res_recompute.json()["data"]
    assert data_recompute["updated_count"] == 2

    # Verify stored coordinate in database
    mol_after = await db["molecules"].find_one({"_id": ObjectId(mol1_id)})
    assert "chemical_space" in mol_after["metadata"]
    assert "x" in mol_after["metadata"]["chemical_space"]

    # Test GET again uses stored coordinate
    res_cs_stored = await async_client.get(
        f"/api/v1/projects/{project_id}/chemical-space",
        headers=auth_headers
    )
    assert res_cs_stored.status_code == 200
    assert res_cs_stored.json()["data"]["method"] == "deterministic_placeholder"

@pytest.mark.asyncio
async def test_similarity_endpoints(async_client, auth_headers, project):
    project_id = project["id"]
    db = get_database()

    # Create dummy molecules
    mol1_id = str(ObjectId())
    mol2_id = str(ObjectId())
    await db["molecules"].insert_many([
        {
            "_id": ObjectId(mol1_id),
            "project_id": ObjectId(project_id),
            "compound_id": "QDF-0001",
            "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
            "mw": 180.16,
            "logp": 1.2,
            "qed": 0.8,
            "status": "uploaded",
            "source": "manual",
            "metadata": {}
        },
        {
            "_id": ObjectId(mol2_id),
            "project_id": ObjectId(project_id),
            "compound_id": "QDF-0002",
            "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O", # exact match
            "mw": 180.16,
            "logp": 1.2,
            "qed": 0.8,
            "status": "uploaded",
            "source": "manual",
            "metadata": {}
        }
    ])

    # 1. Test POST /similarity/search
    search_payload = {
        "query_molecule_id": mol1_id,
        "top_k": 5,
        "min_similarity": 0.0,
        "include_self": False
    }
    res_search = await async_client.post(
        f"/api/v1/projects/{project_id}/similarity/search",
        json=search_payload,
        headers=auth_headers
    )
    assert res_search.status_code == 200
    data_search = res_search.json()["data"]
    assert len(data_search["results"]) == 1
    assert data_search["results"][0]["molecule_id"] == mol2_id
    assert data_search["results"][0]["similarity"] == 1.0

    # 2. Test GET /similarity/matrix
    res_matrix = await async_client.get(
        f"/api/v1/projects/{project_id}/similarity/matrix",
        headers=auth_headers
    )
    assert res_matrix.status_code == 200
    data_matrix = res_matrix.json()["data"]
    assert len(data_matrix["molecules"]) == 2
    assert len(data_matrix["matrix"]) == 2
    assert data_matrix["matrix"][0][0] == 1.0
    assert data_matrix["matrix"][0][1] == 1.0
