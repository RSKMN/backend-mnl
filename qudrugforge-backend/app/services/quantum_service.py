import logging
from typing import Any, Dict, List, Optional, Tuple

import pymongo
from bson import ObjectId

from app.core.exceptions import AppException
from app.repositories.experiment_repository import experiment_repository
from app.repositories.project_repository import project_repository
from app.repositories.quantum_result_repository import quantum_result_repository
from app.repositories.workspace_repository import workspace_repository
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-quantum-service")


class QuantumService:
    async def _check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace",
            )
        return membership

    async def _get_project_and_workspace(
        self, project_id: str, user_id: str
    ) -> Tuple[dict, str]:
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

    async def create_quantum_run(
        self,
        project_id: str,
        user_id: str,
        source_experiment_id: str,
        parameters: Dict[str, Any],
        name: Optional[str] = None,
        simulate: bool = False,
    ) -> dict:
        project, workspace_id = await self._get_project_and_workspace(project_id, user_id)

        source_exp = await experiment_repository.get_experiment_by_id_and_project(
            source_experiment_id, project_id
        )
        if not source_exp:
            raise AppException(
                status_code=404,
                code="SOURCE_EXPERIMENT_NOT_FOUND",
                message=f"Source experiment '{source_experiment_id}' not found in this project",
            )

        source_type = source_exp.get("type")
        if source_type not in ("gnina", "docking"):
            raise AppException(
                status_code=400,
                code="SOURCE_EXPERIMENT_INVALID",
                message="source_experiment_id must reference a GNINA or docking experiment",
            )

        if str(source_exp.get("workspace_id")) != workspace_id:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="Source experiment does not belong to this workspace",
            )

        if not name:
            name = f"Quantum/QML Run - {source_exp.get('name', source_experiment_id)}"

        now = utc_now()
        exp_doc = {
            "workspace_id": ObjectId(workspace_id),
            "project_id": ObjectId(project_id),
            "name": name,
            "type": "quantum",
            "engine": "qml",
            "status": "queued",
            "progress": 0,
            "parameters": {
                "source_experiment_id": source_experiment_id,
                "source_experiment_type": source_type,
                "quantum_parameters": parameters,
            },
            "input_file_ids": list(source_exp.get("output_file_ids", [])),
            "output_file_ids": [],
            "logs": [
                {
                    "timestamp": now,
                    "level": "info",
                    "message": "Quantum/QML run queued",
                    "stage": "queued",
                    "metadata": {
                        "source_experiment_id": source_experiment_id,
                        "source_experiment_type": source_type,
                    },
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
            "updated_at": now,
        }

        await experiment_repository.ensure_indexes()
        created = await experiment_repository.create_experiment(exp_doc)

        return {
            "experiment": created,
            "source_experiment": source_exp,
            "source_experiment_type": source_type,
            "simulate": simulate,
        }

    async def list_quantum_results(
        self,
        project_id: str,
        user_id: str,
        experiment_id: Optional[str] = None,
        result_kind: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Tuple[List[dict], int]:
        await self._get_project_and_workspace(project_id, user_id)

        sort_by = "created_at"
        sort_order = pymongo.ASCENDING
        if result_kind == "prefilter":
            sort_by = "quantum_prefilter_score"
            sort_order = pymongo.DESCENDING
        elif result_kind == "reranking":
            sort_by = "quantum_rank"
            sort_order = pymongo.ASCENDING
        elif result_kind == "qml_scores":
            sort_by = "quantum_kernel_score"
            sort_order = pymongo.DESCENDING

        await quantum_result_repository.ensure_indexes()
        return await quantum_result_repository.list_results(
            project_id=project_id,
            experiment_id=experiment_id,
            result_kind=result_kind,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )


quantum_service = QuantumService()
