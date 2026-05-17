import os
import pytest

@pytest.mark.asyncio
async def test_file_upload_download_lifecycle(
    async_client, auth_headers, project, test_storage_root
):
    project_id = project["id"]
    fasta_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_files", "protein.fasta")

    # 1. Upload file
    with open(fasta_path, "rb") as f:
        res_upload = await async_client.post(
            f"/api/v1/projects/{project_id}/files/upload",
            files={"file": ("protein.fasta", f, "application/octet-stream")},
            data={"file_type": "protein_fasta", "source_module": "project_inputs"},
            headers=auth_headers
        )
    assert res_upload.status_code == 200
    file_data = res_upload.json()["data"]["file"]
    assert file_data["original_filename"] == "protein.fasta"
    assert file_data["file_type"] == "protein_fasta"
    assert "checksum" in file_data
    file_id = file_data["file_id"]

    # 2. Check local file exists in test storage root
    local_path = file_data["local_path"]
    full_local_path = os.path.join(test_storage_root, local_path)
    assert os.path.exists(full_local_path)
    assert os.path.getsize(full_local_path) == file_data["size_bytes"]

    # 3. List project files
    res_list = await async_client.get(f"/api/v1/projects/{project_id}/files", headers=auth_headers)
    assert res_list.status_code == 200
    assert len(res_list.json()["data"]["items"]) >= 1

    # 4. Get file detail
    res_detail = await async_client.get(f"/api/v1/files/{file_id}", headers=auth_headers)
    assert res_detail.status_code == 200
    assert res_detail.json()["data"]["original_filename"] == "protein.fasta"

    # 5. Download file
    res_download = await async_client.get(f"/api/v1/files/{file_id}/download", headers=auth_headers)
    assert res_download.status_code == 200
    assert len(res_download.content) == file_data["size_bytes"]

    # 6. Delete file
    res_delete = await async_client.delete(f"/api/v1/files/{file_id}", headers=auth_headers)
    assert res_delete.status_code == 200

    # 7. Verify both metadata record and local file are deleted
    res_check = await async_client.get(f"/api/v1/files/{file_id}", headers=auth_headers)
    assert res_check.status_code == 404
    assert not os.path.exists(full_local_path)

@pytest.mark.asyncio
async def test_file_extension_rejection(async_client, auth_headers, project):
    project_id = project["id"]
    fasta_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_files", "protein.fasta")

    # Try uploading with a disallowed extension (.exe)
    with open(fasta_path, "rb") as f:
        res_upload = await async_client.post(
            f"/api/v1/projects/{project_id}/files/upload",
            files={"file": ("malicious.exe", f, "application/octet-stream")},
            data={"file_type": "protein_fasta", "source_module": "project_inputs"},
            headers=auth_headers
        )
    assert res_upload.status_code == 400
    assert "UNSUPPORTED_FILE_TYPE" in res_upload.text

@pytest.mark.asyncio
async def test_file_workspace_isolation(async_client, auth_headers, project):
    project_id = project["id"]
    fasta_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_files", "protein.fasta")

    # 1. Upload a file as User A
    with open(fasta_path, "rb") as f:
        res_upload = await async_client.post(
            f"/api/v1/projects/{project_id}/files/upload",
            files={"file": ("isolation.fasta", f, "application/octet-stream")},
            headers=auth_headers
        )
    file_id = res_upload.json()["data"]["file"]["file_id"]

    # 2. Register User B
    b_payload = {
        "email": "userb@example.com",
        "password": "SecurePassword123!",
        "full_name": "User B",
        "workspace_name": "User B Lab"
    }
    res_b_reg = await async_client.post("/api/v1/auth/register", json=b_payload)
    b_token = res_b_reg.json()["data"]["access_token"]
    b_headers = {"Authorization": f"Bearer {b_token}"}

    # 3. User B tries to download User A's file (should be Forbidden 403)
    res_b_download = await async_client.get(f"/api/v1/files/{file_id}/download", headers=b_headers)
    assert res_b_download.status_code == 403
