from fastapi import APIRouter, Depends, Body, Request
from fastapi.security import HTTPAuthorizationCredentials
from app.schemas.auth import RegisterRequest, LoginRequest, RefreshRequest, LogoutRequest, AuthResponse, MeResponse
from app.services.auth_service import auth_service
from app.services.audit_service import audit_service
from app.services.workspace_service import workspace_service
from app.core.dependencies import get_current_active_user, security
from app.schemas.user import UserResponse
from app.schemas.workspace import WorkspaceResponse
from app.core.security import decode_token, create_access_token, create_refresh_token, revoke_token
from app.core.exceptions import AppException
from app.core.rate_limit import limiter
from fastapi import Request
from app.core.config import settings

router = APIRouter(tags=["Auth"])

@router.post("/register")
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register(request: Request, body: RegisterRequest = Body(...)):
    result = await auth_service.register(body)
    return {
        "success": True,
        "data": {
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "token_type": "bearer",
            "user": UserResponse.from_mongo(result["user"]).model_dump(),
            "workspace": WorkspaceResponse.from_mongo(result["workspace"], result["workspace"]["role"]).model_dump()
        },
        "message": "Registration successful"
    }

@router.post("/login")
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(request: Request, body: LoginRequest = Body(...)):
    result = await auth_service.login(body)
    data = {
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "token_type": "bearer",
        "user": UserResponse.from_mongo(result["user"]).model_dump()
    }
    if "workspace" in result:
        data["workspace"] = WorkspaceResponse.from_mongo(result["workspace"], result["workspace"]["role"]).model_dump()
        
    import asyncio
    asyncio.create_task(
        audit_service.log_event(
            action="LOGIN",
            user_id=str(result["user"]["_id"]),
            metadata={"email": body.email}
        )
    )

    return {
        "success": True,
        "data": data,
        "message": "Login successful"
    }

@router.post("/refresh")
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def refresh(request: Request, body: RefreshRequest = Body(...)):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise AppException(status_code=401, code="UNAUTHORIZED", message="Invalid token type")
        
        jti = payload.get("jti")
        from app.core.security import is_token_revoked
        if jti and is_token_revoked(jti):
            raise AppException(status_code=401, code="UNAUTHORIZED", message="Token has been revoked")
            
        user_id = payload.get("sub")
        
        access_token = create_access_token(subject=user_id, email=payload.get("email", ""))
        refresh_token = create_refresh_token(subject=user_id)
        
        return {
            "success": True,
            "data": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer"
            },
            "message": "Token refreshed"
        }
    except Exception:
        raise AppException(status_code=401, code="UNAUTHORIZED", message="Invalid refresh token")

@router.post("/logout")
async def logout(
    request: LogoutRequest = Body(default=LogoutRequest()),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    try:
        access_payload = decode_token(credentials.credentials)
        if access_payload.get("jti"):
            revoke_token(access_payload["jti"], access_payload["exp"])
    except Exception:
        pass  # If access token is invalid, ignore
        
    if request.refresh_token:
        try:
            refresh_payload = decode_token(request.refresh_token)
            if refresh_payload.get("jti"):
                revoke_token(refresh_payload["jti"], refresh_payload["exp"])
        except Exception:
            pass  # If refresh token is invalid, ignore

    user_id = None
    try:
        user_id = decode_token(credentials.credentials).get("sub")
    except Exception:
        pass
        
    if user_id:
        import asyncio
        asyncio.create_task(
            audit_service.log_event(
                action="LOGOUT",
                user_id=user_id
            )
        )

    return {
        "success": True,
        "data": {},
        "message": "Logout successful"
    }

@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_active_user)):
    user_id = str(current_user["_id"])
    workspaces = await workspace_service.get_user_workspaces(user_id)
    
    return {
        "success": True,
        "data": {
            "user": UserResponse.from_mongo(current_user).model_dump(),
            "workspaces": [WorkspaceResponse.from_mongo(ws, ws["role"]).model_dump() for ws in workspaces]
        },
        "message": "Current user fetched"
    }
