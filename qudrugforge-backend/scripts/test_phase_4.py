import asyncio
import os
import sys
import shutil
import io
from pathlib import Path

from fastapi import UploadFile

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId
from app.core.database import connect_to_mongo, close_mongo_connection, ensure_auth_indexes, get_database
from app.repositories.user_repository import user_repository
from app.services.project_service import project_service
from app.services.file_service import file_service
from app.storage.service import storage_service
from app.core.exceptions import AppException
from app.utils.datetime import utc_now
from app.core.config import settings

async def run_tests():
    print("Connecting to MongoDB...")
    await connect_to_mongo()
    await ensure_auth_indexes()
    
    # Ensure startup directory creation works
    print("Ensuring storage directories exist...")
    storage_service.get_provider().ensure_directories()
    
    db = get_database()
    
    # 1. Setup clean test user and workspaces
    print("\n--- 1. Setting up test data ---")
    user_email = "test-phase4@quinfosys.com"
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase4"})
    await db["workspaces"].delete_many({"slug": "other-ws-phase4"})
    
    now = utc_now()
    user_doc = {
        "email": user_email,
        "password_hash": "hashed_pass",
        "full_name": "Test Phase 4 User",
        "status": "active",
        "created_at": now,
        "updated_at": now
    }
    user = await user_repository.create(user_doc)
    user_id = str(user["_id"])
    print(f"Created test user: {user_id}")
    
    # Create target workspace (where user is member)
    ws_doc = {
        "name": "Test Workspace Phase 4",
        "slug": "test-ws-phase4",
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
        "name": "Other Workspace Phase 4",
        "slug": "other-ws-phase4",
        "owner_user_id": ObjectId(),
        "plan": "development",
        "created_at": now,
        "updated_at": now
    }
    other_ws_res = await db["workspaces"].insert_one(other_ws_doc)
    other_workspace_id = str(other_ws_res.inserted_id)
    print(f"Created non-member workspace: {other_workspace_id}")
    
    # Create projects
    project = await project_service.create_project(
        workspace_id=workspace_id,
        name="EGFR NSCLC Project Phase 4",
        description="Phase 4 discovery program",
        disease_type="NSCLC",
        cancer_type="Non-small cell lung cancer",
        user_id=user_id
    )
    project_id = str(project["_id"])
    print(f"Created program project: {project_id}")
    
    # Create another project in other workspace
    other_project_doc = {
        "workspace_id": ObjectId(other_workspace_id),
        "name": "Secret Project",
        "slug": "secret-project",
        "status": "draft",
        "created_by": ObjectId(),
        "created_at": now,
        "updated_at": now
    }
    other_project_res = await db["projects"].insert_one(other_project_doc)
    other_project_id = str(other_project_res.inserted_id)
    
    # 2. Test unsupported file extensions
    print("\n--- 2. Testing Extension Validation ---")
    bad_file = UploadFile(
        filename="malicious.exe",
        file=io.BytesIO(b"executable content")
    )
    try:
        await file_service.upload_file(
            project_id=project_id,
            file=bad_file,
            file_type=None,
            source_module=None,
            metadata=None,
            user_id=user_id
        )
        print("FAIL: Allowed invalid extension .exe!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "UNSUPPORTED_FILE_TYPE"

    # 3. Test valid file upload and type inference
    print("\n--- 3. Testing Upload & Auto-inference ---")
    fasta_content = b">EGFR_HUMAN\nMRPSGTAGAALLALLAALCPASRALEEKKVCQGTSNKLTQLGTFEDHFLSLQRMFNNCEVVLGNLEITYVQRNYDLSFLKTIQEVAGYVLIALNTVERIP"
    fasta_file = UploadFile(
        filename="egfr_sequence.fasta",
        file=io.BytesIO(fasta_content),
        headers={"content-type": "text/plain"}
    )
    
    uploaded = await file_service.upload_file(
        project_id=project_id,
        file=fasta_file,
        file_type=None,
        source_module="protein_ref",
        metadata={"organism": "Homo sapiens"},
        user_id=user_id
    )
    file_id = uploaded["file_id"]
    print(f"SUCCESS: Uploaded FASTA file. Generated ID: {file_id}")
    print(f"  file_type inferred: {uploaded['file_type']}")
    print(f"  stored physical path: {uploaded['local_path']}")
    print(f"  size: {uploaded['size_bytes']} bytes, checksum: {uploaded['checksum']}")
    
    assert uploaded["file_type"] == "protein_fasta"
    assert uploaded["checksum"] is not None
    assert uploaded["size_bytes"] == len(fasta_content)
    assert "malicious" not in uploaded["stored_filename"]
    
    # Verify file physically exists on storage root relative path
    physical_exists = await storage_service.get_provider().exists(uploaded["local_path"])
    print(f"SUCCESS: Physical file exists on disk: {physical_exists}")
    assert physical_exists is True
    
    # Verify MongoDB does not store file bytes
    raw_doc = await db["files"].find_one({"file_id": file_id})
    print(f"SUCCESS: Verified MongoDB doc shape has no raw bytes or content: {'content' not in raw_doc}")
    assert "content" not in raw_doc
    assert "bytes" not in raw_doc
    
    # 4. Test upload with custom/invalid file type
    print("\n--- 4. Testing Custom/Invalid Type Upload ---")
    pdb_file = UploadFile(
        filename="egfr_docked.pdb",
        file=io.BytesIO(b"PDB file content header coordinate lines...")
    )
    try:
        await file_service.upload_file(
            project_id=project_id,
            file=pdb_file,
            file_type="invalid_docking_format",
            source_module=None,
            metadata=None,
            user_id=user_id
        )
        print("FAIL: Allowed invalid file type!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "INVALID_FILE_TYPE"
        
    # Standard custom file_type should succeed
    pdb_file_2 = UploadFile(
        filename="egfr_docked.pdb",
        file=io.BytesIO(b"ATOM      1  N   ALA A   1      11.123  12.345  13.456")
    )
    uploaded_pdb = await file_service.upload_file(
        project_id=project_id,
        file=pdb_file_2,
        file_type="alphafold_structure",
        source_module="targets",
        metadata=None,
        user_id=user_id
    )
    print(f"SUCCESS: Uploaded PDB with custom type 'alphafold_structure'.")
    assert uploaded_pdb["file_type"] == "alphafold_structure"
    
    # 5. Test Access Control - Unauthorized Upload
    print("\n--- 5. Testing Unauthorized Upload ---")
    other_fasta = UploadFile(
        filename="other.fasta",
        file=io.BytesIO(b">TEST\nACGT")
    )
    try:
        await file_service.upload_file(
            project_id=other_project_id,
            file=other_fasta,
            file_type=None,
            source_module=None,
            metadata=None,
            user_id=user_id
        )
        print("FAIL: Allowed uploading to unauthorized workspace project!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "WORKSPACE_ACCESS_DENIED"
        
    # 6. Test list files
    print("\n--- 6. Testing List Files ---")
    items, total = await file_service.list_files(
        project_id=project_id,
        file_type=None,
        source_module=None,
        skip=0,
        limit=10,
        user_id=user_id
    )
    print(f"SUCCESS: Listed {total} files.")
    assert total == 2
    
    # Filter list
    items_filtered, total_filtered = await file_service.list_files(
        project_id=project_id,
        file_type="protein_fasta",
        source_module=None,
        skip=0,
        limit=10,
        user_id=user_id
    )
    print(f"SUCCESS: Listed {total_filtered} files with file_type 'protein_fasta'.")
    assert total_filtered == 1
    
    # 7. Test get file detail & access check
    print("\n--- 7. Testing File Details & Access Checks ---")
    detail = await file_service.get_file_detail(file_id, user_id)
    print(f"SUCCESS: Fetched file detail. original_filename: '{detail['original_filename']}'")
    assert detail["original_filename"] == "egfr_sequence.fasta"
    
    # Unauthorized detail check
    try:
        # Create a dummy metadata record for another workspace
        fake_id = "fake-uuid-123"
        await db["files"].insert_one({
            "file_id": fake_id,
            "project_id": ObjectId(),
            "workspace_id": ObjectId(), # another workspace
            "original_filename": "secret.fasta",
            "local_path": "uploads/secret.fasta"
        })
        await file_service.get_file_detail(fake_id, user_id)
        print("FAIL: Allowed viewing file detail from unauthorized workspace!")
        sys.exit(1)
    except AppException as e:
        print(f"SUCCESS (expected failure): {e.code} - {e.message}")
        assert e.code == "WORKSPACE_ACCESS_DENIED"
        
    # 8. Test file download
    print("\n--- 8. Testing File Download ---")
    download_path, original_filename = await file_service.get_file_download_path(file_id, user_id)
    print(f"SUCCESS: Got download path: '{download_path}', filename: '{original_filename}'")
    assert original_filename == "egfr_sequence.fasta"
    
    with open(download_path, "rb") as f:
        content = f.read()
    assert content == fasta_content
    
    # 9. Test file deletion
    print("\n--- 9. Testing File Deletion ---")
    delete_res = await file_service.delete_file(file_id, user_id)
    print(f"SUCCESS: File deletion return code: {delete_res}")
    assert delete_res is True
    
    # Verify metadata deleted in DB
    refetched = await db["files"].find_one({"file_id": file_id})
    print(f"SUCCESS: Verified DB doc deleted: {refetched is None}")
    assert refetched is None
    
    # Verify physical file deleted from storage
    physical_exists_after = await storage_service.get_provider().exists(uploaded["local_path"])
    print(f"SUCCESS: Verified physical file deleted: {not physical_exists_after}")
    assert physical_exists_after is False
    
    # 10. Test delete file when physical file is already missing
    print("\n--- 10. Testing Delete When Physical File Already Missing ---")
    # Upload one more
    fasta_file_temp = UploadFile(
        filename="temp.fasta",
        file=io.BytesIO(b">TEMP\nACTG")
    )
    uploaded_temp = await file_service.upload_file(
        project_id=project_id,
        file=fasta_file_temp,
        file_type=None,
        source_module=None,
        metadata=None,
        user_id=user_id
    )
    temp_file_id = uploaded_temp["file_id"]
    
    # Manually delete physical file
    os.unlink(await storage_service.get_provider().get_file_path(uploaded_temp["local_path"]))
    
    # Deletion should still succeed and clean up DB
    delete_res_2 = await file_service.delete_file(temp_file_id, user_id)
    print(f"SUCCESS: Deletion succeeded when physical file was already missing: {delete_res_2}")
    
    refetched_temp = await db["files"].find_one({"file_id": temp_file_id})
    assert refetched_temp is None
    
    # Clean up test database entries
    print("\nCleaning up test data from DB...")
    await db["users"].delete_many({"email": user_email})
    await db["workspaces"].delete_many({"slug": "test-ws-phase4"})
    await db["workspaces"].delete_many({"slug": "other-ws-phase4"})
    await db["projects"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["project_inputs"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["workspace_members"].delete_many({"user_id": ObjectId(user_id)})
    await db["files"].delete_many({"workspace_id": ObjectId(workspace_id)})
    await db["files"].delete_many({"file_id": "fake-uuid-123"})
    
    # Remove physical upload files folders created during tests
    ws_path = Path(settings.LOCAL_STORAGE_ROOT) / "uploads" / workspace_id
    if ws_path.exists():
        shutil.rmtree(ws_path)
        
    print("\n===============================")
    print("ALL TESTS PASSED SUCCESSFULLY!!")
    print("===============================")
    
    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(run_tests())
