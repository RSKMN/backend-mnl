import logging
from typing import List, Optional, Tuple

import pymongo
from bson import ObjectId

from app.core.exceptions import AppException
from app.repositories.admet_result_repository import admet_result_repository
from app.repositories.experiment_repository import experiment_repository
from app.repositories.molecule_repository import molecule_repository
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.schemas.admet import ALLOWED_ADMET_MODELS
from app.utils.admet_risk import summarize_admet_results
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-admet-service")


class AdmetService:
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

    async def create_admet_run(
        self,
        project_id: str,
        user_id: str,
        source_molecule_set: str,
        molecule_ids: List[str],
        models: List[str],
        name: Optional[str] = None,
        simulate: bool = False,
    ) -> dict:
        project, workspace_id = await self._get_project_and_workspace(project_id, user_id)

        if source_molecule_set not in ("filtered", "top_candidates", "selected"):
            raise AppException(
                status_code=400,
                code="VALIDATION_ERROR",
                message="source_molecule_set must be filtered, top_candidates, or selected",
            )

        invalid_models = [model for model in models if model not in ALLOWED_ADMET_MODELS]
        if invalid_models:
            raise AppException(
                status_code=400,
                code="VALIDATION_ERROR",
                message=f"Unsupported ADMET models: {invalid_models}",
            )

        molecule_count: Optional[int] = None

        if source_molecule_set == "selected":
            if not molecule_ids:
                raise AppException(
                    status_code=400,
                    code="VALIDATION_ERROR",
                    message="molecule_ids must be non-empty when source_molecule_set is selected",
                )

            invalid_ids = []
            for molecule_id in molecule_ids:
                molecule = await molecule_repository.get_molecule_by_id(molecule_id)
                if not molecule or str(molecule.get("project_id")) != project_id:
                    invalid_ids.append(molecule_id)
                    continue
            if invalid_ids:
                raise AppException(
                    status_code=403,
                    code="MOLECULE_ACCESS_DENIED",
                    message=f"Molecules not found or not in this project: {invalid_ids}",
                )
            molecule_count = len(molecule_ids)
        else:
            query = {"project_id": ObjectId(project_id)}
            if source_molecule_set == "filtered":
                query["status"] = {"$in": ["filtered", "selected"]}
            elif source_molecule_set == "top_candidates":
                query["status"] = "selected"
            molecule_count = await molecule_repository.collection.count_documents(query)

        if not name:
            name = f"ADMET Run - {source_molecule_set}"

        now = utc_now()
        exp_doc = {
            "workspace_id": ObjectId(workspace_id),
            "project_id": ObjectId(project_id),
            "name": name,
            "type": "admet",
            "engine": "admet",
            "status": "queued",
            "progress": 0,
            "parameters": {
                "source_molecule_set": source_molecule_set,
                "molecule_ids": molecule_ids,
                "models": models,
                "molecule_count": molecule_count,
            },
            "input_file_ids": [],
            "output_file_ids": [],
            "logs": [
                {
                    "timestamp": now,
                    "level": "info",
                    "message": "ADMET run queued",
                    "stage": "queued",
                    "metadata": {
                        "source_molecule_set": source_molecule_set,
                        "molecule_count": molecule_count,
                        "models": models,
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
            "molecule_count": molecule_count,
            "simulate": simulate,
        }

    async def list_admet_results(
        self,
        project_id: str,
        user_id: str,
        experiment_id: Optional[str] = None,
        risk_level: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Tuple[List[dict], int]:
        await self._get_project_and_workspace(project_id, user_id)
        await admet_result_repository.ensure_indexes()
        return await admet_result_repository.list_results(
            project_id=project_id,
            experiment_id=experiment_id,
            risk_level=risk_level,
            skip=skip,
            limit=limit,
            sort_by="created_at",
            sort_order=pymongo.ASCENDING,
        )

    async def get_admet_summary(self, project_id: str, user_id: str) -> dict:
        await self._get_project_and_workspace(project_id, user_id)
        await admet_result_repository.ensure_indexes()
        items, total = await admet_result_repository.list_results(
            project_id=project_id,
            skip=0,
            limit=10000,
        )
        summary = summarize_admet_results(items, total=total)
        summary["models"] = sorted(ALLOWED_ADMET_MODELS)
        return summary


admet_service = AdmetService()
