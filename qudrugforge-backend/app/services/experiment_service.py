import logging
from bson import ObjectId
from typing import Optional, List, Dict, Any, Tuple
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

# Repositories
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.repositories.experiment_repository import experiment_repository
from app.repositories.file_metadata_repository import file_metadata_repository

logger = logging.getLogger("qudrugforge-experiment-service")

class ExperimentService:
    async def check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace"
            )
        return membership

    async def create_experiment(
        self,
        project_id: str,
        user_id: str,
        name: str,
        type_str: str,
        engine_str: str,
        parameters: Dict[str, Any],
        input_file_ids: List[str]
    ) -> dict:
        # 1. Fetch project and validate
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )

        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        # 2. Validate input_file_ids if provided
        for file_id in input_file_ids:
            file_meta = await file_metadata_repository.get_metadata_by_file_id(file_id)
            if not file_meta:
                raise AppException(
                    status_code=404,
                    code="FILE_NOT_FOUND",
                    message=f"Input file with ID '{file_id}' was not found."
                )
            # Ensure file belongs to same project/workspace
            if str(file_meta["project_id"]) != project_id or str(file_meta["workspace_id"]) != workspace_id:
                raise AppException(
                    status_code=403,
                    code="FILE_ACCESS_DENIED",
                    message=f"Input file '{file_id}' does not belong to this project or workspace."
                )

        # 3. Create document shape
        now = utc_now()
        doc = {
            "workspace_id": ObjectId(workspace_id),
            "project_id": ObjectId(project_id),
            "name": name,
            "type": type_str,
            "engine": engine_str,
            "status": "queued",
            "progress": 0,
            "parameters": parameters or {},
            "input_file_ids": input_file_ids or [],
            "output_file_ids": [],
            "logs": [
                {
                    "timestamp": now,
                    "level": "info",
                    "message": "Experiment queued",
                    "stage": "queued",
                    "metadata": {}
                }
            ],
            "q_ai_drug_job_id": None,
            "q_ai_drug_run_name": None,
            "import_id": None,
            "error": None,
            "started_at": None,
            "completed_at": None,
            "created_by": ObjectId(user_id),
            "created_at": now,
            "updated_at": now
        }

        # Initialize indexes on collection
        await experiment_repository.ensure_indexes()

        created = await experiment_repository.create_experiment(doc)
        return created

    async def list_experiments(
        self,
        project_id: str,
        user_id: str,
        status: Optional[str] = None,
        type_str: Optional[str] = None,
        engine_str: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[dict], int]:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )

        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        items, total = await experiment_repository.list_experiments(
            project_id=project_id,
            status=status,
            type=type_str,
            engine=engine_str,
            skip=skip,
            limit=limit
        )
        return items, total

    async def get_experiment(self, project_id: str, experiment_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )

        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        experiment = await experiment_repository.get_experiment_by_id_and_project(experiment_id, project_id)
        if not experiment:
            raise AppException(
                status_code=404,
                code="EXPERIMENT_NOT_FOUND",
                message="Experiment not found in this project"
            )
        return experiment

    async def update_experiment(self, project_id: str, experiment_id: str, user_id: str, data: dict) -> dict:
        # Load experiment and validate workspace access
        experiment = await self.get_experiment(project_id, experiment_id, user_id)
        
        # Build update set dictionary
        update_set = {}
        now = utc_now()

        # Core fields allowed for updates
        allowed_keys = {
            "name", "type", "engine", "status", "progress", "parameters",
            "output_file_ids", "q_ai_drug_job_id", "q_ai_drug_run_name",
            "import_id", "error"
        }

        # Status and Progress specific changes
        new_status = data.get("status")
        new_progress = data.get("progress")

        for k, v in data.items():
            if k in allowed_keys and v is not None:
                update_set[k] = v

        if not update_set:
            return experiment

        update_set["updated_at"] = now

        # If status changes, handle timestamp tracking and push logging
        old_status = experiment.get("status")
        if new_status and new_status != old_status:
            # 1. Update running started_at
            if new_status == "running" and not experiment.get("started_at"):
                update_set["started_at"] = now
            # 2. Update completion timestamps
            if new_status in ("completed", "imported", "failed", "cancelled") and not experiment.get("completed_at"):
                update_set["completed_at"] = now

            # Append dynamic status log trace
            log_item = {
                "timestamp": now,
                "level": "info" if new_status != "failed" else "error",
                "message": f"Experiment status transitioned from {old_status} to {new_status}",
                "stage": experiment.get("type", "update"),
                "metadata": {}
            }
            await experiment_repository.append_log(experiment_id, log_item)

        updated = await experiment_repository.update_experiment(experiment_id, update_set)
        if not updated:
            raise AppException(
                status_code=500,
                code="EXPERIMENT_UPDATE_FAILED",
                message="Failed to update experiment record."
            )
        return updated

    async def append_log(self, project_id: str, experiment_id: str, user_id: str, log_data: dict) -> dict:
        # Load experiment and validate workspace access
        await self.get_experiment(project_id, experiment_id, user_id)

        now = utc_now()
        log_item = {
            "timestamp": now,
            "level": log_data.get("level", "info").lower(),
            "message": log_data["message"],
            "stage": log_data.get("stage", "general"),
            "metadata": log_data.get("metadata", {})
        }

        updated = await experiment_repository.append_log(experiment_id, log_item)
        if not updated:
            raise AppException(
                status_code=500,
                code="EXPERIMENT_LOG_FAILED",
                message="Failed to append log entry."
            )
        return updated

    async def cancel_experiment(self, project_id: str, experiment_id: str, user_id: str) -> dict:
        # Load experiment and validate workspace access
        experiment = await self.get_experiment(project_id, experiment_id, user_id)

        current_status = experiment.get("status")
        if current_status in ("completed", "failed", "cancelled", "imported"):
            raise AppException(
                status_code=400,
                code="EXPERIMENT_CANCEL_FAILED",
                message=f"Cannot cancel experiment that is already in terminal state '{current_status}'."
            )

        now = utc_now()
        update_set = {
            "status": "cancelled",
            "completed_at": now,
            "updated_at": now
        }

        # Append cancel trace log
        log_item = {
            "timestamp": now,
            "level": "warning",
            "message": "Experiment manually cancelled by user.",
            "stage": experiment.get("type", "cancel"),
            "metadata": {}
        }
        await experiment_repository.append_log(experiment_id, log_item)

        updated = await experiment_repository.update_experiment(experiment_id, update_set)
        if not updated:
            raise AppException(
                status_code=500,
                code="EXPERIMENT_CANCEL_FAILED",
                message="Failed to cancel experiment."
            )
        return updated

    async def get_summary(self, project_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )

        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        summary = await experiment_repository.summary_by_project(project_id)
        return summary

experiment_service = ExperimentService()
