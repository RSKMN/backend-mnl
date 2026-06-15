import pytest
from httpx import AsyncClient
from unittest.mock import patch

@pytest.mark.asyncio
async def test_metrics_protected_unauthenticated(async_client: AsyncClient):
    """
    Test that /metrics requires authentication.
    """
    response = await async_client.get("/metrics/")
    assert response.status_code == 403

@pytest.mark.asyncio
@patch("app.core.dependencies.get_current_active_user")
async def test_metrics_protected_viewer(mock_user, async_client: AsyncClient, auth_token: str):
    """
    Test that /metrics requires ADMIN system role, rejecting VIEWER.
    """
    mock_user.return_value = {"_id": "123", "system_role": "VIEWER"}
    headers = {"Authorization": f"Bearer {auth_token}"}
    response = await async_client.get("/metrics/", headers=headers)
    assert response.status_code == 403

@pytest.mark.asyncio
@patch("app.core.dependencies.decode_token")
@patch("app.repositories.user_repository.user_repository.get_by_id")
async def test_metrics_protected_admin(mock_get_user, mock_decode, async_client: AsyncClient, auth_token: str):
    """
    Test that /metrics is accessible to ADMIN.
    """
    mock_decode.return_value = {"sub": "123", "type": "access", "jti": "abc"}
    mock_get_user.return_value = {"_id": "123", "system_role": "ADMIN", "status": "active"}
    
    headers = {"Authorization": f"Bearer {auth_token}"}
    response = await async_client.get("/metrics/", headers=headers)
    assert response.status_code == 200
    assert "http_requests_total" in response.text
