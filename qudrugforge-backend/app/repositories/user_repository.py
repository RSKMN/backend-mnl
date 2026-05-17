from bson import ObjectId
from app.core.database import get_database
from typing import Optional

class UserRepository:
    @property
    def collection(self):
        return get_database()["users"]

    async def get_by_id(self, user_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(user_id):
            return None
        return await self.collection.find_one({"_id": ObjectId(user_id)})

    async def get_by_email(self, email: str) -> Optional[dict]:
        return await self.collection.find_one({"email": email.lower()})

    async def create(self, user_doc: dict) -> dict:
        result = await self.collection.insert_one(user_doc)
        return await self.get_by_id(str(result.inserted_id))

user_repository = UserRepository()
