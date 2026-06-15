import pytest
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_root_endpoint(async_client):
    """Test the root endpoint returns running status and correct prefixes."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "QuDrugForge Backend"
    assert data["status"] == "running"

@pytest.mark.asyncio
@patch("app.api.v1.health.redis.Redis.from_url")
@patch("app.core.celery_app.celery_app.control.inspect")
async def test_health_endpoints_degraded(mock_inspect, mock_redis, async_client):
    """
    Test Phase 7B Expanded Health Check:
    Healthy Mongo, Healthy Redis, 0 Workers -> degraded, HTTP 200
    """
    # Mock Redis ping success
    mock_redis_instance = MagicMock()
    mock_redis_instance.ping.return_value = True
    mock_redis.return_value = mock_redis_instance

    # Mock Celery 0 workers active
    mock_inspect_instance = MagicMock()
    mock_inspect_instance.active.return_value = {}
    mock_inspect.return_value = mock_inspect_instance

    res_v1 = await async_client.get("/api/v1/health")
    assert res_v1.status_code == 200
    
    data = res_v1.json()
    assert data["status"] == "degraded"
    assert data["components"]["mongo"] == "healthy"
    assert data["components"]["redis"] == "healthy"
    assert data["components"]["celery"] == "degraded"
    assert data["components"]["storage"] == "healthy"

@pytest.mark.asyncio
async def test_system_info_endpoint(async_client):
    response = await async_client.get("/api/v1/system/info")
    assert response.status_code == 200
    data = response.json()
    assert data["environment"] == "test"
    assert data["mongodb_database"] == "qudrugforge_test"
    assert data["local_storage_root"] == "./storage_test"
