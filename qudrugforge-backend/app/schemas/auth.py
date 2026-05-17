from pydantic import BaseModel, EmailStr, Field, field_validator
from app.schemas.user import UserResponse
from app.schemas.workspace import WorkspaceResponse

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2, max_length=100)
    workspace_name: str = Field(..., min_length=2, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be 72 bytes or fewer.")
        return v

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class AuthResponse(TokenData):
    user: UserResponse
    workspace: WorkspaceResponse

class MeResponse(BaseModel):
    user: UserResponse
    workspaces: list[WorkspaceResponse]
