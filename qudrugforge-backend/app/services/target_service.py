from bson import ObjectId
from typing import Optional, List, Tuple
from app.repositories.project_repository import project_repository
from app.repositories.target_repository import target_repository
from app.repositories.file_metadata_repository import file_metadata_repository
from app.repositories.workspace_repository import workspace_repository
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

class TargetService:
    async def check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace"
            )
        return membership

    async def create_target(self, project_id: str, request_data: dict, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)
        
        # Enforce status options
        status = request_data.get("status") or "candidate"
        allowed_status = ["candidate", "selected", "rejected", "archived"]
        if status not in allowed_status:
            raise AppException(
                status_code=400,
                code="INVALID_TARGET_DATA",
                message=f"Status must be one of {allowed_status}"
            )
            
        # Optional structure file validation
        structure_file_id = request_data.get("structure_file_id")
        if structure_file_id:
            file_meta = await file_metadata_repository.get_by_file_id(structure_file_id)
            if not file_meta:
                raise AppException(
                    status_code=404,
                    code="FILE_NOT_FOUND",
                    message="Structure file not found."
                )
            if str(file_meta["project_id"]) != project_id:
                raise AppException(
                    status_code=403,
                    code="FILE_ACCESS_DENIED",
                    message="Structure file belongs to a different project."
                )
            if str(file_meta["workspace_id"]) != workspace_id:
                raise AppException(
                    status_code=403,
                    code="FILE_ACCESS_DENIED",
                    message="Structure file workspace mismatch."
                )
            allowed_types = ["protein_structure", "alphafold_structure"]
            if file_meta.get("file_type") not in allowed_types:
                raise AppException(
                    status_code=400,
                    code="INVALID_TARGET_DATA",
                    message=f"Structure file must be type: {allowed_types}"
                )

        now = utc_now()
        target_doc = {
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(workspace_id),
            "gene": request_data.get("gene"),
            "uniprot_id": request_data.get("uniprot_id"),
            "protein_name": request_data.get("protein_name"),
            "structure_file_id": structure_file_id,
            "rank_score": request_data.get("rank_score", 0.0),
            "status": status,
            "metadata": request_data.get("metadata") or {},
            "created_by": ObjectId(user_id),
            "created_at": now,
            "updated_at": now
        }
        
        return await target_repository.create_target(target_doc)

    async def list_targets(
        self,
        project_id: str,
        status: Optional[str],
        search: Optional[str],
        skip: int,
        limit: int,
        user_id: str
    ) -> Tuple[List[dict], int]:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        return await target_repository.list_targets(project_id, status, search, skip, limit)

    async def get_target(self, project_id: str, target_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        
        target = await target_repository.get_target_by_id(target_id)
        if not target or str(target["project_id"]) != project_id:
            raise AppException(
                status_code=404,
                code="TARGET_NOT_FOUND",
                message="Target not found"
            )
            
        return target

    async def rank_targets(self, project_id: str, request_data: dict, user_id: str) -> List[dict]:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        
        target_ids = request_data.get("target_ids")
        if target_ids:
            updates = []
            score = 0.95
            for tid in target_ids:
                updates.append((tid, round(max(score, 0.01), 2)))
                score -= 0.05
            
            now = utc_now()
            await target_repository.update_target_rank_scores(updates, now)

        # Return all project targets sorted by rank_score descending
        targets, _ = await target_repository.list_targets(project_id, skip=0, limit=1000)
        return targets

target_service = TargetService()
