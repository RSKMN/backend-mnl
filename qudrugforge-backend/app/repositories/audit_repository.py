import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from bson import ObjectId

from app.core.database import get_database
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-audit-repo")

class AuditRepository:
    def __init__(self):
        self._collection_name = "audit_logs"

    @property
    def collection(self):
        return get_database()[self._collection_name]

    async def insert_event(self, event_doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Append-only insertion of an audit event.
        No update or delete operations are permitted.
        """
        result = await self.collection.insert_one(event_doc)
        event_doc["_id"] = result.inserted_id
        return event_doc

    async def list_events(
        self,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
        skip: int = 0
    ) -> List[Dict[str, Any]]:
        query = {}
        if workspace_id:
            query["workspace_id"] = ObjectId(workspace_id)
        if project_id:
            query["project_id"] = ObjectId(project_id)
        if user_id:
            query["user_id"] = ObjectId(user_id)
        if action:
            query["action"] = action

        cursor = self.collection.find(query).sort("timestamp", -1).skip(skip).limit(limit)
        events = await cursor.to_list(length=limit)
        return events

audit_repository = AuditRepository()
