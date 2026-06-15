import logging
from typing import List, Tuple, Dict

from app.core.exceptions import AppException
from app.repositories.claim_matrix_repository import claim_matrix_repository
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository

logger = logging.getLogger("qudrugforge-claim-matrix-service")

class ClaimMatrixService:
    async def _check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace",
            )
        return membership

    async def _get_project_and_workspace(self, project_id: str, user_id: str) -> Tuple[dict, str]:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found",
            )
        workspace_id = str(project["workspace_id"])
        await self._check_workspace_access(workspace_id, user_id)
        return project, workspace_id

    async def get_project_claim_matrix(self, project_id: str, user_id: str) -> Tuple[List[dict], int]:
        await self._get_project_and_workspace(project_id, user_id)
        await claim_matrix_repository.ensure_indexes()
        return await claim_matrix_repository.get_by_project(project_id=project_id)

    async def get_project_claim_matrix_summary(self, project_id: str, user_id: str) -> Dict:
        await self._get_project_and_workspace(project_id, user_id)
        await claim_matrix_repository.ensure_indexes()
        return await claim_matrix_repository.get_summary(project_id=project_id)

claim_matrix_service = ClaimMatrixService()
