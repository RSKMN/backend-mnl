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
from app.services.target_service import target_service
from app.services.molecule_service import molecule_service
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

async def run_tests():
    print("Connecting to MongoDB...")
    await connect_to_mongo()
    await ensure_auth_indexes()
    
    db = get_database()
    
    # 1. Setup clean test user and workspaces
    print("\n--- 1. Setting up test data ---")
    user_email = "test-phase6@quinfosys.com"
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase6"})
    
    now = utc_now()
    user_doc = {
        "email": user_email,
        "password_hash": "hashed_pass",
        "full_name": "Test Phase 6 User",
        "status": "active",
        "created_at": now,
        "updated_at": now
    }
    user = await user_repository.create(user_doc)
    user_id = str(user["_id"])
    print(f"Created test user: {user_id}")
    
    # Create workspace
    ws_doc = {
        "name": "Test Workspace Phase 6",
        "slug": "test-ws-phase6",
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
        name="EGFR NSCLC Project Phase 6",
        description="Phase 6 scientific endpoints",
        disease_type="NSCLC",
        cancer_type="Non-small cell lung cancer",
        user_id=user_id
    )
    project_id = str(project["_id"])
    print(f"Created project: {project_id}")
    
    # 2. Test Targets endpoints
    print("\n--- 2. Testing Targets endpoints ---")
    
    # 2.1 Create Target 1
    t1_data = {
        "gene": "EGFR",
        "uniprot_id": "P00533",
        "protein_name": "Epidermal growth factor receptor",
        "rank_score": 0.92,
        "status": "selected",
        "metadata": {"relevance": "high"}
    }
    target1 = await target_service.create_target(project_id, t1_data, user_id)
    target1_id = str(target1["_id"])
    print(f"Created target 1: {target1_id} (gene: EGFR)")
    assert target1["gene"] == "EGFR"
    assert target1["status"] == "selected"
    
    # 2.2 Create Target 2
    t2_data = {
        "gene": "ALK",
        "uniprot_id": "Q9UM73",
        "protein_name": "Anaplastic lymphoma kinase",
        "rank_score": 0.81,
        "status": "candidate",
        "metadata": {}
    }
    target2 = await target_service.create_target(project_id, t2_data, user_id)
    target2_id = str(target2["_id"])
    print(f"Created target 2: {target2_id} (gene: ALK)")
    
    # 2.3 List Targets
    targets, total = await target_service.list_targets(project_id, status=None, search=None, skip=0, limit=10, user_id=user_id)
    print(f"Listed targets: count={len(targets)}, total={total}")
    assert total == 2
    
    # 2.4 Get Target Detail
    t_detail = await target_service.get_target(project_id, target1_id, user_id)
    print(f"Fetched target detail gene matches: {t_detail['gene']}")
    assert t_detail["gene"] == "EGFR"
    
    # 2.5 Rank Targets (Placeholder)
    ranked = await target_service.rank_targets(
        project_id=project_id,
        request_data={"target_ids": [target2_id, target1_id]},
        user_id=user_id
    )
    print(f"Ranked targets count: {len(ranked)}")
    # Target 2 should now have score 0.95 and Target 1 score 0.90
    assert ranked[0]["gene"] == "ALK"
    assert ranked[0]["rank_score"] == 0.95
    assert ranked[1]["gene"] == "EGFR"
    assert ranked[1]["rank_score"] == 0.90

    # 3. Test Molecules endpoints via CSV upload & import
    print("\n--- 3. Uploading compound library CSV ---")
    
    csv_content = (
        "SMILES,compound_id,name,MW,LogP,QED,TPSA\n"
        "CCO,QDF-M001,ethanol,46.07,0.5,0.7,20.2\n"
        "CCN,QDF-M002,ethylamine,45.08,0.3,0.6,26.0\n"
        "CC(=O)O,QDF-M003,acetic_acid,60.05,0.2,0.55,37.3\n"
        "CCO,QDF-M001,duplicate_ethanol,46.07,0.5,0.7,20.2\n"
    )
    csv_file = UploadFile(
        filename="library.csv",
        file=io.BytesIO(csv_content.encode("utf-8"))
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
    print(f"Uploaded CSV File ID: {csv_file_id}")
    
    # Import Molecules
    print("\n--- 4. Importing molecules from compound library ---")
    summary = await molecule_service.import_molecules(
        project_id=project_id,
        request_data={
            "source_file_id": csv_file_id,
            "smiles_column": "SMILES",
            "compound_id_column": "compound_id",
            "name_column": "name"
        },
        user_id=user_id
    )
    print(f"Import summary:")
    print(f"  created_count: {summary['created_count']}")
    print(f"  duplicate_count: {summary['duplicate_count']}")
    print(f"  invalid_count: {summary['invalid_count']}")
    assert summary["created_count"] == 3
    assert summary["duplicate_count"] == 1
    
    # 5. List and Filter Molecules
    print("\n--- 5. Listing and Filtering Molecules ---")
    molecules, total_mol = await molecule_service.list_molecules(
        project_id=project_id,
        status=None,
        search=None,
        source_file_id=None,
        skip=0,
        limit=10,
        user_id=user_id
    )
    print(f"Listed molecules: count={len(molecules)}, total={total_mol}")
    assert total_mol == 3
    
    # Get molecule detail
    mol_id = str(molecules[0]["_id"])
    mol_detail = await molecule_service.get_molecule(project_id, mol_id, user_id)
    print(f"Fetched molecule compound_id matches: {mol_detail['compound_id']}")
    assert mol_detail["compound_id"] in ["QDF-M001", "QDF-M002", "QDF-M003"]
    
    # Filter molecules
    filtered = await molecule_service.filter_molecules(
        project_id=project_id,
        criteria={
            "mw_max": 50.0,
            "mark_filtered": True
        },
        user_id=user_id
    )
    print(f"Filtered molecules (MW <= 50.0) count: {len(filtered)}")
    # Ethanol (46.07) and ethylamine (45.08) match, Acetic Acid (60.05) is excluded.
    assert len(filtered) == 2
    assert filtered[0]["status"] == "filtered"
    
    # Clean up test database entries
    print("\nCleaning up test data from DB...")
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase6"})
    await db["projects"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["project_inputs"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["workspace_members"].delete_many({"user_id": ObjectId(user_id)})
    await db["files"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["targets"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["molecules"].delete_many({"workspace_id": ObjectId(workspace_id)})
    
    print("\n===============================")
    print("ALL TESTS PASSED SUCCESSFULLY!!")
    print("===============================")
    
    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(run_tests())
