import pytest

@pytest.mark.asyncio
async def test_root_endpoint(async_client):
    """Test the root endpoint returns running status and correct prefixes."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "QuDrugForge Backend"
    assert data["status"] == "running"

@pytest.mark.asyncio
async def test_health_endpoints(async_client):
    # Test root health
    res_root = await async_client.get("/health")
    assert res_root.status_code == 200
    data_root = res_root.json()
    assert data_root["status"] == "ok"
    assert data_root["database"] == "connected"
    assert data_root["storage"] == "local"

    # Test api/v1/health health
    res_v1 = await async_client.get("/api/v1/health")
    assert res_v1.status_code == 200
    assert res_v1.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_system_info_endpoint(async_client):
    response = await async_client.get("/api/v1/system/info")
    assert response.status_code == 200
    data = response.json()
    assert data["environment"] == "test"
    assert data["mongodb_database"] == "qudrugforge_test"
    assert data["local_storage_root"] == "./storage_test"
