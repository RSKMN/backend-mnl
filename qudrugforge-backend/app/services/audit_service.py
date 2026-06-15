import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.repositories.audit_repository import audit_repository
from app.utils.datetime import utc_now
from bson import ObjectId

logger = logging.getLogger("qudrugforge-audit-service")

class AuditService:
    async def log_event(
        self,
        action: str,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        resource: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Log an audit event.
        """
        event = {
            "timestamp": utc_now(),
            "action": action,
            "resource": resource,
            "metadata": metadata or {}
        }
        
        if user_id:
            event["user_id"] = ObjectId(user_id)
        if workspace_id:
            event["workspace_id"] = ObjectId(workspace_id)
        if project_id:
            event["project_id"] = ObjectId(project_id)
            
        try:
            return await audit_repository.insert_event(event)
        except Exception as e:
            logger.error(f"Failed to write audit log for action {action}: {e}")
            # Do not fail the main request if audit logging fails, just log it.
            return {}

    async def list_events(
        self,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
        skip: int = 0
    ) -> List[Dict[str, Any]]:
        return await audit_repository.list_events(
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            action=action,
            limit=limit,
            skip=skip
        )

audit_service = AuditService()
