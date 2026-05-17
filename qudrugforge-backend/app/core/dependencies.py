from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from app.core.security import decode_token
from app.core.exceptions import AppException
from app.repositories.user_repository import user_repository
from app.repositories.workspace_repository import workspace_repository

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        if user_id is None or token_type != "access":
            raise AppException(status_code=401, code="UNAUTHORIZED", message="Invalid token payload")
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
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not a member of this workspace"
            )
        return membership
    return _require_workspace_member
