import re
from bson import ObjectId
from app.repositories.user_repository import user_repository
from app.repositories.workspace_repository import workspace_repository
from app.schemas.auth import RegisterRequest, LoginRequest
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

def generate_slug(name: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', name).strip('-').lower()
    return slug

class AuthService:
    async def register(self, data: RegisterRequest) -> dict:
        email = data.email.lower()
        existing_user = await user_repository.get_by_email(email)
        if existing_user:
            raise AppException(status_code=400, code="USER_ALREADY_EXISTS", message="Email already registered")

        # Create User
        now = utc_now()
        try:
            hashed_pwd = hash_password(data.password)
        except ValueError as e:
            raise AppException(status_code=422, code="VALIDATION_ERROR", message=str(e))

        user_doc = {
            "email": email,
            "password_hash": hashed_pwd,
            "full_name": data.full_name,
            "status": "active",
            "created_at": now,
            "updated_at": now
        }
        user = await user_repository.create(user_doc)
        user_id = user["_id"]

        # Create Workspace
        slug = generate_slug(data.workspace_name)
        # Handle duplicate slug
        existing_workspace = await workspace_repository.get_workspace_by_slug(slug)
        if existing_workspace:
            slug = f"{slug}-{str(user_id)[:6]}"

        workspace_doc = {
            "name": data.workspace_name,
            "slug": slug,
            "owner_user_id": user_id,
            "plan": "development",
            "created_at": now,
            "updated_at": now
        }
        workspace = await workspace_repository.create_workspace(workspace_doc)

        # Create Membership
        member_doc = {
            "workspace_id": workspace["_id"],
            "user_id": user_id,
            "role": "owner",
            "status": "active",
            "created_at": now
        }
        await workspace_repository.create_member(member_doc)
        
        workspace["role"] = "owner"

        # Generate tokens
        access_token = create_access_token(subject=str(user_id), email=email)
        refresh_token = create_refresh_token(subject=str(user_id))

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": user,
            "workspace": workspace
        }

    async def login(self, data: LoginRequest) -> dict:
        email = data.email.lower()
        user = await user_repository.get_by_email(email)
        if not user or not verify_password(data.password, user["password_hash"]):
            raise AppException(status_code=401, code="INVALID_CREDENTIALS", message="Invalid email or password")
        
        if user.get("status") != "active":
            raise AppException(status_code=403, code="FORBIDDEN", message="User account is disabled")

        workspaces = await workspace_repository.get_user_workspaces(str(user["_id"]))
        selected_workspace = workspaces[0] if workspaces else None

        access_token = create_access_token(subject=str(user["_id"]), email=email)
        refresh_token = create_refresh_token(subject=str(user["_id"]))

        result = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": user
        }
        if selected_workspace:
            result["workspace"] = selected_workspace
            
        return result

auth_service = AuthService()
