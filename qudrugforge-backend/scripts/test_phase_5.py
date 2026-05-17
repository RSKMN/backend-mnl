import asyncio
import os
import sys
import io
from fastapi import UploadFile

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId
from app.core.database import connect_to_mongo, close_mongo_connection, ensure_auth_indexes, get_database
from app.repositories.user_repository import user_repository
from app.services.project_service import project_service
from app.services.file_service import file_service
from app.services.project_input_service import project_input_service
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

async def run_tests():
    print("Connecting to MongoDB...")
    await connect_to_mongo()
    await ensure_auth_indexes()
    
    db = get_database()
    
    # 1. Setup clean test user and workspaces
    print("\n--- 1. Setting up test data ---")
    user_email = "test-phase5@quinfosys.com"
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase5"})
    
    now = utc_now()
    user_doc = {
        "email": user_email,
        "password_hash": "hashed_pass",
        "full_name": "Test Phase 5 User",
        "status": "active",
        "created_at": now,
        "updated_at": now
    }
    user = await user_repository.create(user_doc)
    user_id = str(user["_id"])
    print(f"Created test user: {user_id}")
    
    # Create workspace
    ws_doc = {
        "name": "Test Workspace Phase 5",
        "slug": "test-ws-phase5",
        "owner_user_id": user["_id"],
        "plan": "development",
        "created_at": now,
        "updated_at": now
    }
    ws_res = await db["workspaces"].insert_one(ws_doc)
    workspace_id = str(ws_res.inserted_id)
    print(f"Created workspace: {workspace_id}")
    
    # Create membership
    member_doc = {
        "workspace_id": ObjectId(workspace_id),
        "user_id": ObjectId(user_id),
        "role": "owner",
        "status": "active",
        "created_at": now
    }
    await db["workspace_members"].insert_one(member_doc)
    
    # Create project
    project = await project_service.create_project(
        workspace_id=workspace_id,
        name="EGFR NSCLC Project Phase 5",
        description="Phase 5 scientific input program",
        disease_type="NSCLC",
        cancer_type="Non-small cell lung cancer",
        user_id=user_id
    )
    project_id = str(project["_id"])
    print(f"Created project: {project_id}")
    
    # Upload test scientific files
    print("\n--- 2. Uploading test scientific structure files ---")
    
    # 2.1 Protein structure PDB file
    pdb_file = UploadFile(
        filename="receptor.pdb",
        file=io.BytesIO(b"ATOM      1  N   ALA A   1      11.123  12.345  13.456")
    )
    uploaded_pdb = await file_service.upload_file(
        project_id=project_id,
        file=pdb_file,
        file_type="protein_structure",
        source_module="project_inputs",
        metadata=None,
        user_id=user_id
    )
    pdb_file_id = uploaded_pdb["file_id"]
    print(f"Uploaded PDB File ID: {pdb_file_id} (type: protein_structure)")
    
    # 2.2 Compound library CSV file
    csv_file = UploadFile(
        filename="ligands.csv",
        file=io.BytesIO(b"smiles,id\nCN1CCC[C@H]1c2cccnc2,nicotine")
    )
    uploaded_csv = await file_service.upload_file(
        project_id=project_id,
        file=csv_file,
        file_type="compound_library",
        source_module="project_inputs",
        metadata=None,
        user_id=user_id
    )
    csv_file_id = uploaded_csv["file_id"]
    print(f"Uploaded CSV File ID: {csv_file_id} (type: compound_library)")

    # 3. Test File Assignment & Compatibility
    print("\n--- 3. Testing File Assignment Compatibility Checks ---")
    
    # 3.1 Invalid assignment: assigning compound_library to protein_structure_file_id
    try:
        await project_input_service.assign_files(
            project_id=project_id,
            assignments={"protein_structure_file_id": csv_file_id},
            user_id=user_id
        )
        print("FAIL: Allowed assigning compound library to protein structure field!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "INVALID_INPUT_FILE_TYPE"

    # 3.2 Valid assignment: assigning PDB to protein_structure_file_id and CSV to compound_library_file_id
    assigned = await project_input_service.assign_files(
        project_id=project_id,
        assignments={
            "protein_structure_file_id": pdb_file_id,
            "compound_library_file_id": csv_file_id
        },
        user_id=user_id
    )
    print("SUCCESS: Valid assignments persisted!")
    assert assigned["protein_structure_file_id"] == pdb_file_id
    assert assigned["compound_library_file_id"] == csv_file_id
    
    # 3.3 Test unassigning files (setting to None)
    unassigned = await project_input_service.assign_files(
        project_id=project_id,
        assignments={"protein_structure_file_id": None},
        user_id=user_id
    )
    print("SUCCESS: Unassigned protein_structure_file_id successfully!")
    assert unassigned["protein_structure_file_id"] is None
    assert unassigned["compound_library_file_id"] == csv_file_id
    
    # Assign it back for completeness tests
    await project_input_service.assign_files(
        project_id=project_id,
        assignments={"protein_structure_file_id": pdb_file_id},
        user_id=user_id
    )

    # 4. Test Binding Site Configuration
    print("\n--- 4. Testing Binding Site Configuration & Validation ---")
    
    # 4.1 Update mode: box (valid)
    bs_box = {
        "mode": "box",
        "box": {
            "center_x": 10.2,
            "center_y": 14.1,
            "center_z": -3.4,
            "size_x": 22,
            "size_y": 22,
            "size_z": 22
        }
    }
    updated_bs_1 = await project_input_service.update_binding_site(project_id, bs_box, user_id)
    print("SUCCESS: Updated binding site to valid box config!")
    assert updated_bs_1["binding_site"]["mode"] == "box"
    assert updated_bs_1["binding_site"]["box"]["center_x"] == 10.2
    assert updated_bs_1["binding_site"]["box"]["size_x"] == 22
    
    # 4.2 Update mode: box (invalid negative size)
    bs_box_invalid = {
        "mode": "box",
        "box": {
            "center_x": 0.0, "center_y": 0.0, "center_z": 0.0,
            "size_x": -10.0, "size_y": 20.0, "size_z": 20.0
        }
    }
    try:
        await project_input_service.update_binding_site(project_id, bs_box_invalid, user_id)
        print("FAIL: Allowed negative box sizes!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "INVALID_BINDING_SITE"

    # 4.3 Update mode: residues (valid)
    bs_res = {
        "mode": "residues",
        "residues": ["LYS745", "MET793", "ASP855"]
    }
    updated_bs_2 = await project_input_service.update_binding_site(project_id, bs_res, user_id)
    print("SUCCESS: Updated binding site to residues config!")
    assert updated_bs_2["binding_site"]["mode"] == "residues"
    assert "LYS745" in updated_bs_2["binding_site"]["residues"]
    
    # 4.4 Update mode: residues (invalid empty)
    bs_res_invalid = {
        "mode": "residues",
        "residues": []
    }
    try:
        await project_input_service.update_binding_site(project_id, bs_res_invalid, user_id)
        print("FAIL: Allowed empty residues list!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "INVALID_BINDING_SITE"

    # 5. Test Completeness Readiness Checker Heuristics
    print("\n--- 5. Testing Completeness Heuristics ---")
    
    # Check completeness when we have structure, library, and residues binding site
    report = await project_input_service.check_completeness(project_id, user_id)
    print(f"SUCCESS: Completeness report generated!")
    print(f"  ready_for_docking: {report['ready_for_docking']}")
    print(f"  ready_for_gnina: {report['ready_for_gnina']}")
    print(f"  ready_for_quantum: {report['ready_for_quantum']}")
    print(f"  ready_for_admet: {report['ready_for_admet']}")
    print(f"  ready_for_simulations: {report['ready_for_simulations']}")
    print(f"  ready_for_reporting: {report['ready_for_reporting']}")
    print(f"  overall_ready: {report['overall_ready']}")
    print(f"  warnings: {report['warnings']}")
    
    assert report["ready_for_docking"] is True
    assert report["ready_for_gnina"] is True
    assert report["ready_for_quantum"] is True
    assert report["ready_for_admet"] is True
    assert report["ready_for_reporting"] is True
    assert "quantum" in report["modules"]
    assert report["modules"]["quantum"]["ready"] is True
    
    # Clean up test database entries
    print("\nCleaning up test data from DB...")
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase5"})
    await db["projects"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["project_inputs"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["workspace_members"].delete_many({"user_id": ObjectId(user_id)})
    await db["files"].delete_many({"workspace_id": ObjectId(workspace_id)})
    
    print("\n===============================")
    print("ALL TESTS PASSED SUCCESSFULLY!!")
    print("===============================")
    
    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(run_tests())
