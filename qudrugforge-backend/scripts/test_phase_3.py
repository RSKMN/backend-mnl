import asyncio
import sys
import os

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId
from app.core.database import connect_to_mongo, close_mongo_connection, ensure_auth_indexes, get_database
from app.repositories.user_repository import user_repository
from app.repositories.workspace_repository import workspace_repository
from app.services.project_service import project_service
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
    user_email = "test-phase3@quinfosys.com"
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase3"})
    await db["workspaces"].delete_many({"slug": "other-ws-phase3"})
    
    now = utc_now()
    user_doc = {
        "email": user_email,
        "password_hash": "hashed_pass",
        "full_name": "Test Phase 3 User",
        "status": "active",
        "created_at": now,
        "updated_at": now
    }
    user = await user_repository.create(user_doc)
    user_id = str(user["_id"])
    print(f"Created test user: {user_id}")
    
    # Create target workspace (where user is member)
    ws_doc = {
        "name": "Test Workspace Phase 3",
        "slug": "test-ws-phase3",
        "owner_user_id": user["_id"],
        "plan": "development",
        "created_at": now,
        "updated_at": now
    }
    ws_res = await db["workspaces"].insert_one(ws_doc)
    workspace_id = str(ws_res.inserted_id)
    print(f"Created member workspace: {workspace_id}")
    
    # Create membership
    member_doc = {
        "workspace_id": ObjectId(workspace_id),
        "user_id": ObjectId(user_id),
        "role": "owner",
        "status": "active",
        "created_at": now
    }
    await db["workspace_members"].insert_one(member_doc)
    
    # Create other workspace (where user is NOT member)
    other_ws_doc = {
        "name": "Other Workspace Phase 3",
        "slug": "other-ws-phase3",
        "owner_user_id": ObjectId(),
        "plan": "development",
        "created_at": now,
        "updated_at": now
    }
    other_ws_res = await db["workspaces"].insert_one(other_ws_doc)
    other_workspace_id = str(other_ws_res.inserted_id)
    print(f"Created non-member workspace: {other_workspace_id}")
    
    # 2. Test Access Control & Create Project
    print("\n--- 2. Testing Project Creation & Access Control ---")
    
    # Should fail due to WORKSPACE_ACCESS_DENIED
    try:
        await project_service.create_project(
            workspace_id=other_workspace_id,
            name="Secret Project",
            description="No access",
            disease_type="None",
            cancer_type="None",
            user_id=user_id
        )
        print("FAIL: Created project in unauthorized workspace!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "WORKSPACE_ACCESS_DENIED"
        
    # Should succeed
    project = await project_service.create_project(
        workspace_id=workspace_id,
        name="EGFR NSCLC Discovery Program",
        description="Targeted oncology discovery project",
        disease_type="NSCLC",
        cancer_type="Non-small cell lung cancer",
        user_id=user_id
    )
    project_id = str(project["_id"])
    print(f"SUCCESS: Created project {project_id} with slug '{project['slug']}'")
    assert project["slug"] == "egfr-nsclc-discovery-program"
    assert project["status"] == "draft"

    
    # Verify project_inputs document automatically created
    inputs = await project_input_service.get_project_inputs(project_id, user_id)
    print("SUCCESS: Auto-created default project_inputs:")
    print(f"  disease_type: {inputs.get('disease_type')}")
    print(f"  binding_site mode: {inputs['binding_site']['mode']}")
    assert inputs["disease_type"] == "NSCLC"
    assert inputs["binding_site"]["mode"] == "box"
    assert inputs["binding_site"]["box"]["size_x"] == 20.0
    
    # Test Slug Uniqueness inside same workspace
    project_dup = await project_service.create_project(
        workspace_id=workspace_id,
        name="EGFR NSCLC Discovery Program",
        description="Second project",
        disease_type="NSCLC",
        cancer_type="Non-small cell lung cancer",
        user_id=user_id
    )
    print(f"SUCCESS: Created duplicate name project. Slug generated: '{project_dup['slug']}'")
    assert project_dup["slug"] == "egfr-nsclc-discovery-program-2"

    
    # 3. Test List Projects
    print("\n--- 3. Testing List Projects ---")
    items, total = await project_service.list_projects(
        workspace_id=workspace_id,
        status=None,
        search=None,
        skip=0,
        limit=10,
        user_id=user_id
    )
    print(f"SUCCESS: Listed {total} projects.")
    assert total >= 2
    
    # Test search
    items, total = await project_service.list_projects(
        workspace_id=workspace_id,
        status=None,
        search="EGFR",
        skip=0,
        limit=10,
        user_id=user_id
    )
    print(f"SUCCESS: Listed {total} projects matching search 'EGFR'.")
    assert total >= 2
    
    # 4. Test Update Project
    print("\n--- 4. Testing Update Project ---")
    updated_project = await project_service.update_project(
        project_id=project_id,
        update_data={"name": "EGFR NSCLC Program Redux", "status": "active"},
        user_id=user_id
    )
    print(f"SUCCESS: Updated project name and status.")
    print(f"  new name: {updated_project['name']}")
    print(f"  new slug: {updated_project['slug']}")
    print(f"  new status: {updated_project['status']}")
    assert updated_project["name"] == "EGFR NSCLC Program Redux"
    assert updated_project["slug"] == "egfr-nsclc-program-redux"
    assert updated_project["status"] == "active"
    
    # Test Invalid Project Status
    try:
        await project_service.update_project(
            project_id=project_id,
            update_data={"status": "invalid_status"},
            user_id=user_id
        )
        print("FAIL: Allowed invalid project status!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "INVALID_PROJECT_STATUS"
        
    # 5. Test Update Project Inputs
    print("\n--- 5. Testing Update Project Inputs ---")
    inputs_update = {
        "target_gene": "EGFR",
        "uniprot_id": "P00533",
        "disease_type": "NSCLC Adenocarcinoma"
    }
    updated_inputs = await project_input_service.update_project_inputs(
        project_id=project_id,
        update_data=inputs_update,
        user_id=user_id
    )
    print("SUCCESS: Updated project inputs.")
    print(f"  target_gene: {updated_inputs['target_gene']}")
    print(f"  disease_type: {updated_inputs['disease_type']}")
    assert updated_inputs["target_gene"] == "EGFR"
    assert updated_inputs["uniprot_id"] == "P00533"
    assert updated_inputs["disease_type"] == "NSCLC Adenocarcinoma"
    
    # Verify disease_type sync'ed back to project
    refetched_project = await project_service.get_project(project_id, user_id)
    print(f"SUCCESS: Synced disease_type back to project: {refetched_project['disease_type']}")
    assert refetched_project["disease_type"] == "NSCLC Adenocarcinoma"
    
    # Test Binding Site Update
    print("\n--- 6. Testing Binding Site Update ---")
    bs_update = {
        "mode": "box",
        "box": {
            "center_x": 10.2,
            "center_y": 14.1,
            "center_z": -3.4,
            "size_x": 22.0,
            "size_y": 22.0,
            "size_z": 22.0
        }
    }
    updated_inputs_bs = await project_input_service.update_binding_site(
        project_id=project_id,
        binding_site_data=bs_update,
        user_id=user_id
    )
    print("SUCCESS: Updated binding site.")
    print(f"  binding site mode: {updated_inputs_bs['binding_site']['mode']}")
    print(f"  binding site box center_x: {updated_inputs_bs['binding_site']['box']['center_x']}")
    assert updated_inputs_bs["binding_site"]["box"]["center_x"] == 10.2
    assert updated_inputs_bs["binding_site"]["box"]["size_x"] == 22.0
    
    # Test negative size validation
    bs_invalid = {
        "mode": "box",
        "box": {
            "center_x": 10.2,
            "center_y": 14.1,
            "center_z": -3.4,
            "size_x": -1.0,
            "size_y": 22.0,
            "size_z": 22.0
        }
    }
    try:
        await project_input_service.update_binding_site(
            project_id=project_id,
            binding_site_data=bs_invalid,
            user_id=user_id
        )
        print("FAIL: Allowed negative box size!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "VALIDATION_ERROR"
        
    # 7. Test Overview
    print("\n--- 7. Testing Project Overview ---")
    overview = await project_service.get_project_overview(project_id, user_id)
    print("SUCCESS: Fetched project overview.")
    print(f"  project state: {overview['project']['status']}")
    print(f"  input_summary.has_target_gene: {overview['input_summary']['has_target_gene']}")
    print(f"  input_summary.binding_site_configured: {overview['input_summary']['binding_site_configured']}")
    print(f"  next_steps: {overview['next_steps']}")
    assert overview["input_summary"]["has_target_gene"] is True
    assert overview["input_summary"]["binding_site_configured"] is True
    
    # 8. Test Timeline
    print("\n--- 8. Testing Project Timeline ---")
    timeline = await project_service.get_project_timeline(project_id, user_id)
    print("SUCCESS: Fetched timeline events:")
    for ev in timeline["items"]:
        print(f"  - [{ev['type']}] {ev['title']} at {ev['timestamp']}")
    assert len(timeline["items"]) >= 2  # project_created and project_updated / inputs_updated
    
    # 9. Test Soft Delete / Archive
    print("\n--- 9. Testing Project Archiving ---")
    archived = await project_service.archive_project(project_id, user_id)
    assert archived is True
    
    refetched_project = await project_service.get_project(project_id, user_id)
    print(f"SUCCESS: Soft deleted status is: '{refetched_project['status']}'")
    assert refetched_project["status"] == "archived"
    
    # Listing shouldn't show it by default
    items, total = await project_service.list_projects(
        workspace_id=workspace_id,
        status=None,
        search=None,
        skip=0,
        limit=10,
        user_id=user_id
    )
    print(f"SUCCESS: Listed projects total after archiving: {total}")
    # Verify the archived project is not in items
    for item in items:
        assert str(item["_id"]) != project_id
        
    # Clean up test database entries
    print("\nCleaning up test data from DB...")
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase3"})
    await db["workspaces"].delete_many({"slug": "other-ws-phase3"})
    await db["projects"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["project_inputs"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["workspace_members"].delete_many({"user_id": ObjectId(user_id)})
    
    print("\n===============================")
    print("ALL TESTS PASSED SUCCESSFULLY!!")
    print("===============================")
    
    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(run_tests())
