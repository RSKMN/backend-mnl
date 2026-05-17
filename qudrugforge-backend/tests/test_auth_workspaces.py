import pytest

@pytest.mark.asyncio
async def test_register_and_duplicate_handling(async_client):
    payload = {
        "email": "registerme@example.com",
        "password": "Password123!",
        "full_name": "New User",
        "workspace_name": "Primary Lab"
    }
    
    # 1. First register
    res1 = await async_client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["success"] is True
    assert data1["data"]["user"]["email"] == "registerme@example.com"
    assert "access_token" in data1["data"]

    # 2. Duplicate registration should be rejected
    res2 = await async_client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 400
    assert res2.json()["success"] is False

@pytest.mark.asyncio
async def test_login_success_and_failures(async_client):
    # Register first
    reg_payload = {
        "email": "loginuser@example.com",
        "password": "Password123!",
        "full_name": "Login User",
        "workspace_name": "Login Lab"
    }
    await async_client.post("/api/v1/auth/register", json=reg_payload)

    # 1. Valid login
    login_payload = {
        "email": "loginuser@example.com",
        "password": "Password123!"
    }
    res_login = await async_client.post("/api/v1/auth/login", json=login_payload)
    assert res_login.status_code == 200
    data_login = res_login.json()
    assert data_login["success"] is True
    assert "access_token" in data_login["data"]

    # 2. Invalid password login
    bad_pwd_payload = {
        "email": "loginuser@example.com",
        "password": "WrongPassword!"
    }
    res_bad_pwd = await async_client.post("/api/v1/auth/login", json=bad_pwd_payload)
    assert res_bad_pwd.status_code == 401

    # 3. Invalid user login
    bad_user_payload = {
        "email": "nonexistent@example.com",
        "password": "Password123!"
    }
    res_bad_user = await async_client.post("/api/v1/auth/login", json=bad_user_payload)
    assert res_bad_user.status_code == 401

@pytest.mark.asyncio
async def test_me_and_protected_access(async_client, auth_headers):
    # 1. /me with token
    res_me = await async_client.get("/api/v1/auth/me", headers=auth_headers)
    assert res_me.status_code == 200
    data_me = res_me.json()
    assert data_me["success"] is True
    assert data_me["data"]["user"]["email"] == "testuser@example.com"

    # 2. /me without token should fail
    res_unauth = await async_client.get("/api/v1/auth/me")
    assert res_unauth.status_code == 401

@pytest.mark.asyncio
async def test_workspaces_crud_lifecycle(async_client, auth_headers, workspace):
    # 1. Get workspaces list
    res_list = await async_client.get("/api/v1/workspaces", headers=auth_headers)
    assert res_list.status_code == 200
    data_list = res_list.json()
    assert len(data_list["data"]) >= 1
    assert data_list["data"][0]["id"] == workspace["id"]

    # 2. Create workspace
    create_payload = {
        "name": "Secondary Bio-Lab"
    }
    res_create = await async_client.post("/api/v1/workspaces", json=create_payload, headers=auth_headers)
    assert res_create.status_code == 200
    new_ws = res_create.json()["data"]
    assert new_ws["name"] == "Secondary Bio-Lab"

    # 3. Fetch workspace details
    res_detail = await async_client.get(f"/api/v1/workspaces/{new_ws['id']}", headers=auth_headers)
    assert res_detail.status_code == 200
    assert res_detail.json()["data"]["name"] == "Secondary Bio-Lab"

    # 4. Select workspace
    res_select = await async_client.post(f"/api/v1/workspaces/{new_ws['id']}/select", headers=auth_headers)
    assert res_select.status_code == 200
    assert res_select.json()["data"]["id"] == new_ws["id"]
