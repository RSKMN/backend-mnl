from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from app.utils.object_id import PyObjectId

class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    status: str = "active"

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    password_hash: str
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

class UserResponse(UserBase):
    id: str

    @classmethod
    def from_mongo(cls, data: dict):
        return cls(
            id=str(data["_id"]),
            email=data["email"],
            full_name=data["full_name"],
            status=data.get("status", "active")
        )
