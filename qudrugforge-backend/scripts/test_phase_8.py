import asyncio
import os
import sys
from pathlib import Path
from bson import ObjectId

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import connect_to_mongo, close_mongo_connection, ensure_auth_indexes, get_database
from app.repositories.user_repository import user_repository
from app.services.project_service import project_service
from app.services.artifact_import_service import artifact_import_service
from app.utils.datetime import utc_now

async def run_tests():
    print("Connecting to MongoDB...")
    await connect_to_mongo()
    await ensure_auth_indexes()
    
    db = get_database()
    
    # 1. Setup clean test user and workspace
    print("\n--- 1. Setting up test workspace and project ---")
    user_email = "test-phase8@quinfosys.com"
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase8"})
    
    now = utc_now()
    user_doc = {
        "email": user_email,
        "password_hash": "hashed_pass",
        "full_name": "Test Phase 8 User",
        "status": "active",
        "created_at": now,
        "updated_at": now
    }
    user = await user_repository.create(user_doc)
    user_id = str(user["_id"])
    print(f"Created test user: {user_id}")
    
    # Create workspace
    ws_doc = {
        "name": "Test Workspace Phase 8",
        "slug": "test-ws-phase8",
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
        name="EGFR NSCLC Project Phase 8",
        description="Phase 8 artifact importer testing",
        disease_type="NSCLC",
        cancer_type="Non-small cell lung cancer",
        user_id=user_id
    )
    project_id = str(project["_id"])
    print(f"Created project: {project_id}")

    # 2. Test Safe Path Traversal Resolution
    print("\n--- 2. Testing safe path boundaries and traversal ---")
    try:
        await artifact_import_service.import_artifacts(
            project_id=project_id,
            user_id=user_id,
            run_name="../../../../../any_path"
        )
        assert False, "Expected path traversal validation to raise AppException"
    except Exception as e:
        print(f"SUCCESS (traversal blocked): code={getattr(e, 'code', None)}, message={getattr(e, 'message', None)}")
        assert getattr(e, "code", None) == "Q_AI_DRUG_OUTPUT_PATH_UNSAFE"

    # Test missing run directory
    try:
        await artifact_import_service.import_artifacts(
            project_id=project_id,
            user_id=user_id,
            run_name="non_existent_run_directory_xyz"
        )
        assert False, "Expected missing run directory to raise AppException"
    except Exception as e:
        print(f"SUCCESS (missing directory handled): code={getattr(e, 'code', None)}, message={getattr(e, 'message', None)}")
        assert getattr(e, "code", None) == "Q_AI_DRUG_OUTPUT_NOT_FOUND"

    # 3. Perform Q-AI-Drug Run Import
    print("\n--- 3. Running Artifact Importer ---")
    # Let's import the cancer_proof_v1 run directory we just unrar'd!
    result = await artifact_import_service.import_artifacts(
        project_id=project_id,
        user_id=user_id,
        run_name="cancer_proof_v1"
    )
    
    print("\nImport Summary Results:")
    print(f"  Success! Import Session ID: {result['import_id']}")
    print(f"  Run Name: {result['run_name']}")
    print(f"  Source Dir: {result['source_dir']}")
    print(f"  Imported Files Count: {len(result['imported_files'])}")
    print(f"  Missing Files Count: {len(result['missing_files'])}")
    print(f"  Parsed Collections Counts:")
    for k, v in result["parsed_collections"].items():
        print(f"    - {k}: {v}")
    
    # 4. Database Persistence Assertions
    print("\n--- 4. Performing Database Persistence Checks ---")
    
    # Check registered files in "files"
    files_count = await db["files"].count_documents({"project_id": ObjectId(project_id)})
    print(f"Registered file metadata records count: {files_count}")
    assert files_count > 0

    # Verify physical file existence in storage
    registered_files = await db["files"].find({"project_id": ObjectId(project_id)}).to_list(length=10)
    for rf in registered_files:
        p = Path("storage") / rf["local_path"]
        assert p.exists(), f"Physical file missing in storage: {p}"
    print("SUCCESS: All file metadata records have verified physical storage counterparts!")

    # Check parsed molecules in "molecules"
    mol_count = await db["molecules"].count_documents({"project_id": ObjectId(project_id)})
    print(f"Molecules count: {mol_count}")
    assert mol_count > 0, "No molecules were parsed and saved"

    # Check docking results
    docking_count = await db["docking_results"].count_documents({"project_id": ObjectId(project_id)})
    print(f"Docking results count: {docking_count}")
    assert docking_count > 0, "No docking results were parsed and saved"

    # Check gnina results
    gnina_count = await db["gnina_results"].count_documents({"project_id": ObjectId(project_id)})
    print(f"GNINA results count: {gnina_count}")
    assert gnina_count > 0, "No GNINA results were parsed and saved"

    # Check simulation results
    sim_count = await db["simulation_results"].count_documents({"project_id": ObjectId(project_id)})
    print(f"Simulation results count: {sim_count}")
    assert sim_count > 0, "No simulation results were parsed and saved"

    # Check quantum results
    quantum_count = await db["quantum_results"].count_documents({"project_id": ObjectId(project_id)})
    print(f"Quantum results count: {quantum_count}")
    assert quantum_count > 0, "No quantum results were merged and saved"

    # Verify quantum results details
    sample_quantum = await db["quantum_results"].find_one({"project_id": ObjectId(project_id)})
    assert sample_quantum is not None
    assert "qm_descriptors" in sample_quantum
    assert len(sample_quantum["qm_descriptors"]) > 0
    assert "quantum_prefilter_score" in sample_quantum
    assert "quantum_kernel_score" in sample_quantum
    print("SUCCESS: Merged Quantum document checked successfully!")

    # Check report
    report_count = await db["reports"].count_documents({"project_id": ObjectId(project_id)})
    print(f"Reports count: {report_count}")
    assert report_count > 0, "No reports were parsed and saved"

    # 5. Clean up test database entries and physical files
    print("\nCleaning up database entries...")
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase8"})
    await db["projects"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["project_inputs"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["workspace_members"].delete_many({"user_id": ObjectId(user_id)})
    await db["files"].delete_many({"project_id": ObjectId(project_id)})
    await db["molecules"].delete_many({"project_id": ObjectId(project_id)})
    await db["docking_results"].delete_many({"project_id": ObjectId(project_id)})
    await db["gnina_results"].delete_many({"project_id": ObjectId(project_id)})
    await db["quantum_results"].delete_many({"project_id": ObjectId(project_id)})
    await db["simulation_results"].delete_many({"project_id": ObjectId(project_id)})
    await db["reports"].delete_many({"project_id": ObjectId(project_id)})
    
    # Remove physical test folder in storage
    test_storage_dir = Path("storage") / "artifacts" / workspace_id
    if test_storage_dir.exists():
        shutil.rmtree(test_storage_dir)
        print("Cleaned up copied storage artifacts folder.")

    test_reports_dir = Path("storage") / "reports" / workspace_id
    if test_reports_dir.exists():
        shutil.rmtree(test_reports_dir)
        print("Cleaned up copied storage reports folder.")

    print("\n=================================")
    print("PHASE 8 SMOKE TESTS COMPLETED!!")
    print("=================================")
    
    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(run_tests())
