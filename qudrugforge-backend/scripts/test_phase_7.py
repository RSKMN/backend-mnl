import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import httpx

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId
from app.core.database import connect_to_mongo, close_mongo_connection, ensure_auth_indexes, get_database
from app.repositories.user_repository import user_repository
from app.services.project_service import project_service
from app.services.q_ai_drug_service import q_ai_drug_service
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

# Custom Async Mock for httpx request
class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super(AsyncMock, self).__call__(*args, **kwargs)

async def run_tests():
    print("Connecting to MongoDB...")
    await connect_to_mongo()
    await ensure_auth_indexes()
    
    db = get_database()
    
    # 1. Setup clean test user and workspace
    print("\n--- 1. Setting up test data ---")
    user_email = "test-phase7@quinfosys.com"
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase7"})
    
    now = utc_now()
    user_doc = {
        "email": user_email,
        "password_hash": "hashed_pass",
        "full_name": "Test Phase 7 User",
        "status": "active",
        "created_at": now,
        "updated_at": now
    }
    user = await user_repository.create(user_doc)
    user_id = str(user["_id"])
    print(f"Created test user: {user_id}")
    
    # Create workspace
    ws_doc = {
        "name": "Test Workspace Phase 7",
        "slug": "test-ws-phase7",
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
        name="EGFR NSCLC Project Phase 7",
        description="Phase 7 scientific compute adapter",
        disease_type="NSCLC",
        cancer_type="Non-small cell lung cancer",
        user_id=user_id
    )
    project_id = str(project["_id"])
    print(f"Created project: {project_id}")
    
    # 2. Test Q-AI-DRUG Health Scenarios
    print("\n--- 2. Testing Q-AI-DRUG Health Scenarios ---")
    
    # 2.1 Online/Available Mock Check
    print("Testing health route with cluster ONLINE...")
    mock_res_online = MagicMock(spec=httpx.Response)
    mock_res_online.status_code = 200
    mock_res_online.json.return_value = {"status": "ok", "gpu_status": "active", "cores_used": 16}
    
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_res_online
        
        health_state = await q_ai_drug_service.health()
        print(f"Health response online: available={health_state['available']}, base_url={health_state['base_url']}")
        assert health_state["available"] is True
        assert health_state["health"]["status"] == "ok"
        assert health_state["error"] is None
        
    # 2.2 Offline/Unavailable Mock Check
    print("Testing health route with cluster OFFLINE...")
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.side_effect = httpx.ConnectError("Connection refused")
        
        health_state = await q_ai_drug_service.health()
        print(f"Health response offline: available={health_state['available']}, error={health_state['error']}")
        assert health_state["available"] is False
        assert health_state["health"] is None
        assert "Connection refused" in health_state["error"]

    # 3. Test project-scoped adapter routes under normal conditions
    print("\n--- 3. Testing normalized adapter routes ---")
    
    mock_res_candidates = MagicMock(spec=httpx.Response)
    mock_res_candidates.status_code = 200
    mock_res_candidates.json.return_value = {
        "items": [
            {"candidate_id": "QDF-C01", "docking_score": -9.2, "smiles": "CC1=C(C=C(C=C1)NC2=NC=CC(=N2)N3CCN(CC3)C)C(=O)NC4=CC=C(C=C4)C"},
            {"candidate_id": "QDF-C02", "docking_score": -8.8, "smiles": "CNC(=O)C1=CC=CC=C1SC2=CC3=C(C=C2)N=C(N3)C=CC4=CC=CC=C4"}
        ]
    }
    
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_res_candidates
        
        normalized = await q_ai_drug_service.get_top_candidates(project_id, user_id)
        print("Normalized Top Candidates shape matches criteria:")
        print(f"  project_id: {normalized['project_id']}")
        print(f"  source: {normalized['source']}")
        print(f"  items count: {len(normalized['items'])}")
        print(f"  last_synced_at: {normalized['last_synced_at']}")
        
        assert normalized["project_id"] == project_id
        assert normalized["source"] == "q-ai-drug"
        assert len(normalized["items"]) == 2
        assert "last_synced_at" in normalized
        assert normalized["raw"]["items"][0]["candidate_id"] == "QDF-C01"

    # 4. Test error handling when project-scoped requests fail
    print("\n--- 4. Testing adapter failures and errors mapping ---")
    
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.side_effect = httpx.ConnectError("Connection refused")
        
        try:
            await q_ai_drug_service.get_top_candidates(project_id, user_id)
            assert False, "Expected AppException was not raised"
        except AppException as e:
            print(f"SUCCESS (expected failure): code={e.code}, status_code={e.status_code}, message={e.message}")
            assert e.code == "Q_AI_DRUG_UNAVAILABLE"
            assert e.status_code == 503
            
    # Clean up test database entries
    print("\nCleaning up test data from DB...")
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase7"})
    await db["projects"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["project_inputs"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["workspace_members"].delete_many({"user_id": ObjectId(user_id)})
    
    print("\n===============================")
    print("ALL TESTS PASSED SUCCESSFULLY!!")
    print("===============================")
    
    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(run_tests())
