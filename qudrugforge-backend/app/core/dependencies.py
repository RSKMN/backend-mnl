from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from app.core.security import decode_token, is_token_revoked
from app.core.exceptions import AppException
from app.repositories.user_repository import user_repository
from app.repositories.workspace_repository import workspace_repository
from app.services.audit_service import audit_service
import asyncio

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        jti: str = payload.get("jti")
        
        if user_id is None or token_type != "access":
            raise AppException(status_code=401, code="UNAUTHORIZED", message="Invalid token payload")
            
        if jti and is_token_revoked(jti):
            raise AppException(status_code=401, code="UNAUTHORIZED", message="Token has been revoked")
    except JWTError:
        raise AppException(status_code=401, code="UNAUTHORIZED", message="Could not validate credentials")
        
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise AppException(status_code=404, code="USER_NOT_FOUND", message="User not found")
        
    return user

async def get_current_active_user(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("status") != "active":
        raise AppException(status_code=403, code="FORBIDDEN", message="Inactive user")
    return current_user

def require_workspace_member():
    async def _require_workspace_member(
        workspace_id: str,
        current_user: dict = Depends(get_current_active_user)
    ) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, str(current_user["_id"]))
        if not membership:
            asyncio.create_task(
                audit_service.log_event(
                    action="RBAC_DENIED",
                    user_id=str(current_user["_id"]),
                    workspace_id=workspace_id,
                    metadata={"reason": "Not a workspace member"}
                )
            )
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not a member of this workspace"
            )
        return membership
    return _require_workspace_member

def require_workspace_role(allowed_roles: list[str]):
    """Ensure the user possesses one of the allowed roles in the workspace."""
    async def _require_workspace_role(
        workspace_id: str,
        current_user: dict = Depends(get_current_active_user)
    ) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, str(current_user["_id"]))
        if not membership:
            asyncio.create_task(
                audit_service.log_event(
                    action="RBAC_DENIED",
                    user_id=str(current_user["_id"]),
                    workspace_id=workspace_id,
                    metadata={"reason": "Not a workspace member"}
                )
            )
            raise AppException(status_code=403, code="WORKSPACE_ACCESS_DENIED", message="User is not a member of this workspace")
            
        role = membership.get("role", "viewer").upper()
        if role != "OWNER" and role not in allowed_roles:
            asyncio.create_task(
                audit_service.log_event(
                    action="RBAC_DENIED",
                    user_id=str(current_user["_id"]),
                    workspace_id=workspace_id,
                    metadata={"reason": f"Required one of roles {allowed_roles}, got {role}"}
                )
            )
            raise AppException(status_code=403, code="WORKSPACE_ACCESS_DENIED", message=f"Required one of roles {allowed_roles}")
        return membership
    return _require_workspace_role

def require_global_admin(current_user: dict = Depends(get_current_active_user)) -> dict:
    role = current_user.get("system_role", "VIEWER").upper()
    if role != "ADMIN":
        asyncio.create_task(
            audit_service.log_event(
                action="RBAC_DENIED",
                user_id=str(current_user["_id"]),
                metadata={"reason": f"Global ADMIN privileges required, got {role}"}
            )
        )
        raise AppException(status_code=403, code="FORBIDDEN", message="Global ADMIN privileges required")
    return current_user
