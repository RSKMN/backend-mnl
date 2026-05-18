"""Phase 14 Simulations/MD Backend API and Importer Tests."""

import os
import shutil
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId

from app.core.config import settings
from app.integrations.q_ai_drug_client import QAiDrugClientError
from app.utils.datetime import utc_now
from app.utils.simulation_stability import compute_stability_score, classify_stability


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _create_target(async_client, auth_headers, project_id, pdb_file_id):
    """Create a test EGFR target and return its data dict."""
    payload = {
        "gene": "EGFR",
        "uniprot_id": "P00533",
        "protein_name": "Epidermal growth factor receptor",
        "structure_file_id": pdb_file_id,
        "rank_score": 0.90,
        "status": "candidate",
    }
    res = await async_client.post(
        f"/api/v1/projects/{project_id}/targets",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 200, f"Target creation failed: {res.text}"
    return res.json()["data"]


async def _import_molecules(async_client, auth_headers, project_id, csv_file_id):
    """Import molecules from uploaded ligands CSV and return summary."""
    payload = {
        "source_file_id": csv_file_id,
        "smiles_column": "canonical_smiles",
        "compound_id_column": "compound_id",
    }
    res = await async_client.post(
        f"/api/v1/projects/{project_id}/molecules/import",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 200, f"Molecule import failed: {res.text}"
    return res.json()["data"]


async def _set_binding_site(async_client, auth_headers, project_id):
    """Set a valid binding site in project_inputs."""
    payload = {
        "binding_site": {
            "mode": "box",
            "box": {
                "center_x": 10.0,
                "center_y": 10.0,
                "center_z": 10.0,
                "size_x": 20.0,
                "size_y": 20.0,
                "size_z": 20.0,
            },
        }
    }
    res = await async_client.patch(
        f"/api/v1/projects/{project_id}/inputs/binding-site",
        json=payload["binding_site"],
        headers=auth_headers,
    )
    assert res.status_code == 200, f"Binding site set failed: {res.text}"


async def _create_docking_run(
    async_client,
    auth_headers,
    project_id,
    uploaded_pdb_file,
    uploaded_ligands_csv,
):
    """Create a valid docking run and return its data."""
    target = await _create_target(async_client, auth_headers, project_id, uploaded_pdb_file["file_id"])
    await _import_molecules(async_client, auth_headers, project_id, uploaded_ligands_csv["file_id"])
    await _set_binding_site(async_client, auth_headers, project_id)

    payload = {
        "target_id": target["id"],
        "compound_selection": {"mode": "all"},
        "engine": "vina",
        "parameters": {"exhaustiveness": 8, "num_modes": 9},
    }
    res = await async_client.post(
        f"/api/v1/projects/{project_id}/docking/runs",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["data"]


async def _create_gnina_run(
    async_client,
    auth_headers,
    project_id,
    uploaded_pdb_file,
    uploaded_ligands_csv,
):
    """Create a valid GNINA run and return its data."""
    docking = await _create_docking_run(
        async_client,
        auth_headers,
        project_id,
        uploaded_pdb_file,
        uploaded_ligands_csv,
    )
    
    payload = {
        "source_docking_experiment_id": docking["experiment_id"],
        "top_n": 10,
        "parameters": {"cnn_scoring": True, "exhaustiveness": 8},
    }
    
    with patch(
        "app.services.gnina_service.q_ai_drug_client.start_gnina",
        new_callable=AsyncMock,
        side_effect=QAiDrugClientError("Unavailable", status_code=503),
    ):
        response = await async_client.post(
            f"/api/v1/projects/{project_id}/gnina/runs",
            json=payload,
            headers=auth_headers,
        )
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ─── Tests ────────────────────────────────────────────────────────────────────

# 1. protected simulation routes reject missing token
@pytest.mark.asyncio
async def test_simulation_protected_routes_require_auth(async_client, project):
    project_id = project["id"]
    fake_id = str(ObjectId())

    endpoints = [
        ("POST", f"/api/v1/projects/{project_id}/simulations/runs"),
        ("GET",  f"/api/v1/projects/{project_id}/simulations/results"),
        ("GET",  f"/api/v1/projects/{project_id}/simulations/stability"),
        ("GET",  f"/api/v1/projects/{project_id}/simulations/trajectories"),
        ("GET",  f"/api/v1/projects/{project_id}/simulations/trajectories/{fake_id}"),
    ]

    for method, url in endpoints:
        if method == "POST":
            res = await async_client.post(url, json={})
        else:
            res = await async_client.get(url)
        assert res.status_code in (401, 403, 422), (
            f"Expected auth error for {method} {url}, got {res.status_code}: {res.text}"
        )


# 2. valid simulation run with source docking experiment creates experiment type=simulation
@pytest.mark.asyncio
async def test_create_simulation_run_valid_docking(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    project_id = project["id"]
    docking = await _create_docking_run(
        async_client, auth_headers, project_id, uploaded_pdb_file, uploaded_ligands_csv
    )

    payload = {
        "simulation_type": "md",
        "engine": "gromacs",
        "source_experiment_id": docking["experiment_id"],
        "parameters": {"duration": 10.0, "temperature": 300.0},
        "name": "EGFR Vina Simulation",
        "simulate": False
    }

    res = await async_client.post(
        f"/api/v1/projects/{project_id}/simulations/runs",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert "experiment_id" in data
    assert data["status"] == "queued"
    assert data["simulation_type"] == "md"
    assert data["engine"] == "gromacs"
    assert data["source_experiment_id"] == docking["experiment_id"]
    assert data["source_experiment_type"] == "docking"

    # Query the experiment directly
    res_exp = await async_client.get(
        f"/api/v1/projects/{project_id}/experiments/{data['experiment_id']}",
        headers=auth_headers,
    )
    assert res_exp.status_code == 200
    exp = res_exp.json()["data"]
    assert exp["type"] == "simulation"
    assert exp["engine"] == "gromacs"


# 3. valid simulation run with source GNINA experiment creates experiment type=simulation
@pytest.mark.asyncio
async def test_create_simulation_run_valid_gnina(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    project_id = project["id"]
    gnina = await _create_gnina_run(
        async_client, auth_headers, project_id, uploaded_pdb_file, uploaded_ligands_csv
    )

    payload = {
        "simulation_type": "md",
        "engine": "openmm",
        "source_experiment_id": gnina["experiment_id"],
        "parameters": {"duration": 5.0, "temperature": 310.0},
        "name": "EGFR GNINA Simulation",
        "simulate": False
    }

    res = await async_client.post(
        f"/api/v1/projects/{project_id}/simulations/runs",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert "experiment_id" in data
    assert data["status"] == "queued"
    assert data["source_experiment_type"] == "gnina"


# 4. invalid source_experiment_id rejected
@pytest.mark.asyncio
async def test_create_simulation_run_invalid_source(async_client, auth_headers, project):
    project_id = project["id"]
    fake_exp_id = str(ObjectId())

    payload = {
        "simulation_type": "md",
        "engine": "gromacs",
        "source_experiment_id": fake_exp_id,
        "parameters": {"duration": 10.0, "temperature": 300.0},
        "simulate": False
    }

    res = await async_client.post(
        f"/api/v1/projects/{project_id}/simulations/runs",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 404
    assert "SOURCE_EXPERIMENT_NOT_FOUND" in res.text


# 5. source experiment from another project rejected
@pytest.mark.asyncio
async def test_create_simulation_run_foreign_source(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    project_id = project["id"]
    docking = await _create_docking_run(
        async_client, auth_headers, project_id, uploaded_pdb_file, uploaded_ligands_csv
    )

    # Create another project
    res_proj = await async_client.post(
        "/api/v1/projects",
        json={
            "workspace_id": project["workspace_id"],
            "name": "Second Project",
            "description": "Another oncology project",
            "disease_type": "Cancer",
            "cancer_type": "Lung"
        },
        headers=auth_headers
    )
    assert res_proj.status_code == 200
    foreign_proj_id = res_proj.json()["data"]["id"]

    # Try to start simulation in foreign project linking the first project's docking experiment
    payload = {
        "simulation_type": "md",
        "engine": "gromacs",
        "source_experiment_id": docking["experiment_id"],
        "parameters": {"duration": 10.0, "temperature": 300.0},
        "simulate": False
    }

    res = await async_client.post(
        f"/api/v1/projects/{foreign_proj_id}/simulations/runs",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 404
    assert "SOURCE_EXPERIMENT_NOT_FOUND" in res.text


# 6. invalid simulation_type rejected
@pytest.mark.asyncio
async def test_create_simulation_run_invalid_type(async_client, auth_headers, project):
    project_id = project["id"]
    payload = {
        "simulation_type": "invalid_type",
        "engine": "gromacs",
        "parameters": {},
        "simulate": False
    }
    res = await async_client.post(
        f"/api/v1/projects/{project_id}/simulations/runs",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code in (400, 422)


# 7. invalid engine rejected
@pytest.mark.asyncio
async def test_create_simulation_run_invalid_engine(async_client, auth_headers, project):
    project_id = project["id"]
    payload = {
        "simulation_type": "md",
        "engine": "invalid_engine",
        "parameters": {},
        "simulate": False
    }
    res = await async_client.post(
        f"/api/v1/projects/{project_id}/simulations/runs",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code in (400, 422)


# 8. invalid duration/temperature rejected
@pytest.mark.asyncio
async def test_create_simulation_run_invalid_parameters(async_client, auth_headers, project):
    project_id = project["id"]

    # Test invalid duration
    payload = {
        "simulation_type": "md",
        "engine": "gromacs",
        "parameters": {"duration": -5.0},
        "simulate": False
    }
    res = await async_client.post(
        f"/api/v1/projects/{project_id}/simulations/runs",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code in (400, 422)

    # Test invalid temperature
    payload = {
        "simulation_type": "md",
        "engine": "gromacs",
        "parameters": {"temperature": 0},
        "simulate": False
    }
    res = await async_client.post(
        f"/api/v1/projects/{project_id}/simulations/runs",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code in (400, 422)


# 9. results route returns simulation_results records
@pytest.mark.asyncio
async def test_list_simulation_results(async_client, auth_headers, project, test_db):
    project_id = project["id"]
    now = utc_now()

    # Seed simulation_results doc directly in mock database
    await test_db["simulation_results"].insert_one({
        "project_id": ObjectId(project_id),
        "workspace_id": ObjectId(project["workspace_id"]),
        "experiment_id": ObjectId(),
        "compound_id": "CAND-MD-01",
        "smiles": "CCN",
        "md_stability_score": 0.85,
        "rmsd": 1.2,
        "rmsf": 0.3,
        "stability_class": "stable",
        "status": "imported",
        "created_at": now,
        "updated_at": now
    })

    res = await async_client.get(
        f"/api/v1/projects/{project_id}/simulations/results",
        headers=auth_headers
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["total"] == 1
    item = data["items"][0]
    assert item["compound_id"] == "CAND-MD-01"
    assert item["stability_score"] == 0.85
    assert item["stability_class"] == "stable"


# 10. stability route returns RMSD/RMSF/stability fields
@pytest.mark.asyncio
async def test_get_simulation_stability(async_client, auth_headers, project, test_db):
    project_id = project["id"]
    now = utc_now()
    experiment_id = ObjectId()

    # Seed multiple simulation results
    await test_db["simulation_results"].insert_many([
        {
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(project["workspace_id"]),
            "experiment_id": experiment_id,
            "compound_id": "CAND-MD-01",
            "smiles": "CCN",
            "md_stability_score": 0.88,
            "rmsd": 1.1,
            "rmsf": 0.25,
            "stability_class": "stable",
            "status": "imported",
            "created_at": now,
            "updated_at": now
        },
        {
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(project["workspace_id"]),
            "experiment_id": experiment_id,
            "compound_id": "CAND-MD-02",
            "smiles": "CCO",
            "md_stability_score": 0.40,
            "rmsd": 3.5,
            "rmsf": 0.85,
            "stability_class": "unstable",
            "status": "imported",
            "created_at": now,
            "updated_at": now
        }
    ])

    res = await async_client.get(
        f"/api/v1/projects/{project_id}/simulations/stability",
        params={"experiment_id": str(experiment_id)},
        headers=auth_headers
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["total"] == 2
    assert data["stable"] == 1
    assert data["unstable"] == 1
    assert data["average_rmsd"] is not None
    assert data["average_rmsf"] is not None
    assert len(data["chart_data"]) == 2
    assert len(data["top_candidates"]) == 2


# 11. trajectories route returns registered file metadata/download URL
@pytest.mark.asyncio
async def test_list_simulation_trajectories(async_client, auth_headers, project, test_db, uploaded_pdb_file):
    project_id = project["id"]
    file_id = uploaded_pdb_file["file_id"]

    # Update existing file metadata in the mock DB to make it a trajectory
    await test_db["files"].update_one(
        {"file_id": file_id},
        {"$set": {
            "file_type": "simulation_trajectory",
            "source_module": "simulations",
        }}
    )

    res = await async_client.get(
        f"/api/v1/projects/{project_id}/simulations/trajectories",
        headers=auth_headers
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["file_id"] == file_id
    assert "download_url" in item
    assert f"/api/v1/files/{file_id}/download" in item["download_url"]


# 12. single trajectory endpoint resolves file metadata/download URL
@pytest.mark.asyncio
async def test_get_simulation_trajectory(async_client, auth_headers, project, test_db, uploaded_pdb_file):
    project_id = project["id"]
    file_id = uploaded_pdb_file["file_id"]

    # Update existing file metadata in the mock DB to make it a trajectory
    await test_db["files"].update_one(
        {"file_id": file_id},
        {"$set": {
            "file_type": "simulation_trajectory",
            "source_module": "simulations",
        }}
    )

    res = await async_client.get(
        f"/api/v1/projects/{project_id}/simulations/trajectories/{file_id}",
        headers=auth_headers
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["file_id"] == file_id
    assert "download_url" in data
    assert f"/api/v1/files/{file_id}/download" in data["download_url"]


# 13. stability classifier computes stable/moderate/unstable correctly
def test_stability_classifier_logic():
    # compute_stability_score unit test
    assert compute_stability_score(stability_score=0.9) == 0.9
    assert compute_stability_score(stability_score=1.5) == 1.0
    assert compute_stability_score(stability_score=-0.2) == 0.0

    # compute score from rmsd/rmsf
    # rmsd = 1.4 (average is 1.4/5.0 = 0.28, component = 0.72)
    # rmsf = 0.25 (average is 0.25/3.0 = 0.0833, component = 0.9167)
    # average of components = 0.81835
    score = compute_stability_score(rmsd_avg=1.4, rmsf_avg=0.25)
    assert score is not None
    assert abs(score - 0.8183) < 0.001

    # classify_stability unit test
    assert classify_stability(0.85) == "stable"
    assert classify_stability(0.60) == "moderate"
    assert classify_stability(0.35) == "unstable"
    assert classify_stability(None) == "unknown"


# 14. imported md/stability.csv appears in /simulations/stability
# 15. imported trajectory files are registered and visible through /simulations/trajectories
@pytest.mark.asyncio
async def test_imported_simulations_artifacts_visible(
    async_client, auth_headers, project, test_db
):
    project_id = project["id"]

    # First, make sure the mock output directory has the files and structure needed.
    # In conftest, Q_AI_DRUG_OUTPUT_ROOT points to: tests/utils/sample_q_ai_drug_outputs.
    # We will copy a sample .xtc or .pdb file inside the mock md directory if it doesn't exist
    # to test trajectory registration.
    md_test_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "utils",
        "sample_q_ai_drug_outputs",
        "cancer_proof_v1",
        "md"
    )
    traj_path = os.path.join(md_test_dir, "traj.xtc")
    struct_path = os.path.join(md_test_dir, "prod.pdb")

    # Create empty dummy files to simulate trajectories and structures
    with open(traj_path, "w") as f:
        f.write("mock trajectory data")
    with open(struct_path, "w") as f:
        f.write("mock structure data")

    try:
        # Trigger q-ai-drug artifact import
        import_payload = {
            "run_name": "cancer_proof_v1",
            "source_output_dir": None,
            "experiment_id": None,
        }
        res_import = await async_client.post(
            f"/api/v1/projects/{project_id}/q-ai-drug/import-artifacts",
            json=import_payload,
            headers=auth_headers,
        )
        assert res_import.status_code == 200, f"Import failed: {res_import.text}"

        # 14. Verify imported md/stability.csv appears in /simulations/stability
        res_stability = await async_client.get(
            f"/api/v1/projects/{project_id}/simulations/stability",
            headers=auth_headers
        )
        assert res_stability.status_code == 200
        stab_data = res_stability.json()["data"]
        # In our seed stability.csv: we have 4 candidates (cand_001, cand_002, cand_003, cand_005)
        assert stab_data["total"] >= 4
        # cand_001 (rmsd_avg=1.4, rmsf_avg=0.25 -> stable)
        assert stab_data["stable"] >= 1

        # 15. Verify imported trajectory files are registered and visible
        res_traj = await async_client.get(
            f"/api/v1/projects/{project_id}/simulations/trajectories",
            headers=auth_headers
        )
        assert res_traj.status_code == 200
        traj_data = res_traj.json()["data"]
        assert traj_data["total"] >= 1
        filenames = [item["original_filename"] for item in traj_data["items"]]
        assert "traj.xtc" in filenames

    finally:
        # Cleanup dummy files
        if os.path.exists(traj_path):
            os.remove(traj_path)
        if os.path.exists(struct_path):
            os.remove(struct_path)


# 16. importer skips cleanly if no MD columns exist
@pytest.mark.asyncio
async def test_importer_skips_cleanly_no_md_columns(async_client, auth_headers, project):
    project_id = project["id"]

    # Temporarily rename stability.csv to backup and write a csv with no MD columns
    md_test_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "utils",
        "sample_q_ai_drug_outputs",
        "cancer_proof_v1",
        "md"
    )
    stab_csv = os.path.join(md_test_dir, "stability.csv")
    stab_backup = os.path.join(md_test_dir, "stability.csv.bak")

    shutil.move(stab_csv, stab_backup)

    try:
        # Write dummy CSV with NO MD/stability columns
        with open(stab_csv, "w") as f:
            f.write("compound_id,some_other_column\ncand_001,hello\ncand_002,world\n")

        # Trigger import
        import_payload = {
            "run_name": "cancer_proof_v1",
            "source_output_dir": None,
            "experiment_id": None,
        }
        res_import = await async_client.post(
            f"/api/v1/projects/{project_id}/q-ai-drug/import-artifacts",
            json=import_payload,
            headers=auth_headers,
        )
        assert res_import.status_code == 200
        summary = res_import.json()["data"]
        assert "warnings" in summary
        # Assert warning is present or logged cleanly
        assert any("no md" in w.lower() or "stability columns" in w.lower() for w in summary["warnings"])

    finally:
        # Restore backup
        if os.path.exists(stab_csv):
            os.remove(stab_csv)
        shutil.move(stab_backup, stab_csv)


# 17. q-ai-drug unavailable handled cleanly if tested
@pytest.mark.asyncio
async def test_q_ai_drug_unavailable_handled_cleanly(
    async_client, auth_headers, project, uploaded_pdb_file, uploaded_ligands_csv
):
    project_id = project["id"]
    docking = await _create_docking_run(
        async_client, auth_headers, project_id, uploaded_pdb_file, uploaded_ligands_csv
    )

    payload = {
        "simulation_type": "md",
        "engine": "q_ai_drug",
        "source_experiment_id": docking["experiment_id"],
        "parameters": {"duration": 10.0, "temperature": 300.0},
        "simulate": True
    }

    # Patch start_simulation to raise a 404/503 Client Error (unavailable)
    with patch(
        "app.integrations.q_ai_drug_client.QAiDrugClient.start_simulation",
        new_callable=AsyncMock,
        side_effect=QAiDrugClientError("Not Found", status_code=404),
    ):
        res = await async_client.post(
            f"/api/v1/projects/{project_id}/simulations/runs",
            json=payload,
            headers=auth_headers,
        )

    # It must return 200 and enqueue the job successfully, handling the unavailability gracefully
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["status"] == "queued"
