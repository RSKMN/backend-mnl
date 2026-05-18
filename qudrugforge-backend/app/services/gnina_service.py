import logging
import pymongo
from typing import Optional, List, Tuple, Dict, Any
from bson import ObjectId

from app.core.exceptions import AppException
from app.utils.datetime import utc_now

# Repositories
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.repositories.experiment_repository import experiment_repository
from app.repositories.file_metadata_repository import file_metadata_repository
from app.repositories.gnina_result_repository import gnina_result_repository

# q-ai-drug client
from app.integrations.q_ai_drug_client import q_ai_drug_client, QAiDrugClientError

logger = logging.getLogger("qudrugforge-gnina-service")


class GninaService:
    # ─── Access helpers ───────────────────────────────────────────────────────

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

    # ─── Create GNINA run ─────────────────────────────────────────────────────

    async def create_gnina_run(
        self,
        project_id: str,
        user_id: str,
        source_docking_experiment_id: str,
        top_n: int,
        parameters: Dict[str, Any],
        name: Optional[str] = None,
        simulate: bool = False,
    ) -> dict:
        """
        Validate inputs, create an experiment record of type 'gnina' with
        status 'queued', attempt a non-blocking q-ai-drug GNINA start call,
        and return immediately.

        Direct q-ai-drug GNINA execution: attempted here if q-ai-drug exposes
        /research/gnina/start. As of Phase 11, this route does not exist in
        q-ai-drug-new, so the call fails gracefully and the experiment stays
        queued. Results flow in through the artifact importer (Phase 8/10).
        Full execution orchestration is Phase 20.
        """
        project, workspace_id = await self._get_project_and_workspace(project_id, user_id)

        # 1. Validate source docking experiment
        source_exp = await experiment_repository.get_experiment_by_id_and_project(
            source_docking_experiment_id, project_id
        )
        if not source_exp:
            raise AppException(
                status_code=404,
                code="SOURCE_DOCKING_EXPERIMENT_NOT_FOUND",
                message=f"Source docking experiment '{source_docking_experiment_id}' not found in this project",
            )

        if source_exp.get("type") != "docking":
            raise AppException(
                status_code=400,
                code="SOURCE_DOCKING_EXPERIMENT_INVALID",
                message=(
                    f"Source experiment must be of type 'docking', "
                    f"got '{source_exp.get('type')}'"
                ),
            )

        if str(source_exp.get("workspace_id")) != workspace_id:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="Source docking experiment does not belong to this workspace",
            )

        # 2. Validate top_n
        if top_n < 1 or top_n > 1000:
            raise AppException(
                status_code=400,
                code="INVALID_TOP_N",
                message="top_n must be between 1 and 1000",
            )

        # 3. Build experiment name
        source_name = source_exp.get("name", "Unknown Docking Run")
        if not name:
            name = f"GNINA Rescoring — {source_name}"

        # 4. Collect source docking output files as inputs (if any)
        input_file_ids = list(source_exp.get("output_file_ids", []))

        # 5. Create experiment document
        now = utc_now()
        exp_doc = {
            "workspace_id": ObjectId(workspace_id),
            "project_id": ObjectId(project_id),
            "name": name,
            "type": "gnina",
            "engine": "gnina",
            "status": "queued",
            "progress": 0,
            "parameters": {
                "source_docking_experiment_id": source_docking_experiment_id,
                "top_n": top_n,
                "gnina_parameters": parameters,
            },
            "input_file_ids": input_file_ids,
            "output_file_ids": [],
            "logs": [
                {
                    "timestamp": now,
                    "level": "info",
                    "message": "GNINA run queued",
                    "stage": "queued",
                    "metadata": {
                        "source_docking_experiment_id": source_docking_experiment_id,
                        "top_n": top_n,
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
        experiment_id = str(created["_id"])

        # 6. Attempt q-ai-drug GNINA start (non-blocking, best-effort)
        q_ai_drug_job_id = None
        q_ai_drug_available = False

        try:
            start_payload = {
                "experiment_id": experiment_id,
                "source_docking_experiment_id": source_docking_experiment_id,
                "top_n": top_n,
                **parameters,
            }
            q_response = await q_ai_drug_client.start_gnina(start_payload)
            q_ai_drug_job_id = q_response.get("job_id")
            q_ai_drug_available = True

            # Update experiment with q-ai-drug job info
            update_fields: Dict[str, Any] = {
                "q_ai_drug_job_id": q_ai_drug_job_id,
                "updated_at": utc_now(),
            }
            if q_ai_drug_job_id:
                update_fields["status"] = "running"
                update_fields["started_at"] = utc_now()

            await experiment_repository.collection.update_one(
                {"_id": ObjectId(experiment_id)},
                {"$set": update_fields},
            )
            await experiment_repository.append_log(experiment_id, {
                "timestamp": utc_now(),
                "level": "info",
                "message": f"q-ai-drug GNINA job started: {q_ai_drug_job_id}",
                "stage": "running",
                "metadata": {"q_ai_drug_response": q_response},
            })
            logger.info(f"[gnina] q-ai-drug accepted GNINA job {q_ai_drug_job_id} for experiment {experiment_id}")

        except Exception as e:
            # q-ai-drug start is unavailable or not yet implemented — keep queued gracefully.
            # Handles: QAiDrugClientError (404/503), httpx errors, and test mocks.
            err_msg = getattr(e, "message", str(e))
            err_code = getattr(e, "status_code", None)
            logger.info(
                f"[gnina] q-ai-drug GNINA start unavailable ({err_code}): {err_msg}. "
                f"Experiment {experiment_id} stays queued. Awaiting artifact import."
            )
            await experiment_repository.append_log(experiment_id, {
                "timestamp": utc_now(),
                "level": "warning",
                "message": (
                    "q-ai-drug GNINA start endpoint not available. "
                    "Experiment stays queued. Import artifacts via /q-ai-drug/import-artifacts to populate results."
                ),
                "stage": "queued",
                "metadata": {"q_ai_drug_error": err_msg, "status_code": err_code},
            })

        # Re-fetch the created experiment to return current state
        updated_exp = await experiment_repository.get_experiment_by_id_and_project(
            experiment_id, project_id
        )

        return {
            "experiment": updated_exp or created,
            "q_ai_drug_job_id": q_ai_drug_job_id,
            "q_ai_drug_available": q_ai_drug_available,
        }

    # ─── List GNINA runs ──────────────────────────────────────────────────────

    async def list_gnina_runs(
        self,
        project_id: str,
        user_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[dict], int]:
        await self._get_project_and_workspace(project_id, user_id)
        items, total = await experiment_repository.list_experiments(
            project_id=project_id,
            status=status,
            type="gnina",
            engine=None,
            skip=skip,
            limit=limit,
        )
        return items, total

    # ─── Get single GNINA run ─────────────────────────────────────────────────

    async def get_gnina_run(
        self,
        project_id: str,
        experiment_id: str,
        user_id: str,
    ) -> dict:
        await self._get_project_and_workspace(project_id, user_id)

        experiment = await experiment_repository.get_experiment_by_id_and_project(
            experiment_id, project_id
        )
        if not experiment:
            raise AppException(
                status_code=404,
                code="EXPERIMENT_NOT_FOUND",
                message="GNINA run not found in this project",
            )
        if experiment.get("type") != "gnina":
            raise AppException(
                status_code=404,
                code="EXPERIMENT_NOT_FOUND",
                message="This experiment is not a GNINA run",
            )
        return experiment

    # ─── GNINA Status ─────────────────────────────────────────────────────────

    async def get_gnina_status(
        self,
        project_id: str,
        user_id: str,
        experiment_id: Optional[str] = None,
    ) -> dict:
        project, workspace_id = await self._get_project_and_workspace(project_id, user_id)

        # Resolve experiment — provided or latest gnina experiment in project
        experiment = None
        if experiment_id:
            experiment = await experiment_repository.get_experiment_by_id_and_project(
                experiment_id, project_id
            )
            if not experiment or experiment.get("type") != "gnina":
                raise AppException(
                    status_code=404,
                    code="EXPERIMENT_NOT_FOUND",
                    message="GNINA experiment not found in this project",
                )
        else:
            # Get latest gnina experiment for project
            items, total = await experiment_repository.list_experiments(
                project_id=project_id,
                status=None,
                type="gnina",
                engine=None,
                skip=0,
                limit=1,
            )
            if items:
                experiment = items[0]

        local_status = "no_runs"
        local_progress = 0
        exp_id_str = None
        updated_at = None
        q_ai_drug_job_id = None

        if experiment:
            local_status = experiment.get("status", "queued")
            local_progress = experiment.get("progress", 0)
            exp_id_str = str(experiment["_id"])
            updated_at = experiment.get("updated_at")
            q_ai_drug_job_id = experiment.get("q_ai_drug_job_id")

        # Probe q-ai-drug for live status if we have a job_id
        q_ai_drug_info: Optional[dict] = None
        if q_ai_drug_job_id:
            try:
                raw = await q_ai_drug_client.get_gnina_status(
                    params={"job_id": q_ai_drug_job_id}
                )
                q_ai_drug_info = {
                    "available": True,
                    "status": raw.get("status"),
                    "job_id": q_ai_drug_job_id,
                    "raw": raw,
                }
            except QAiDrugClientError as e:
                q_ai_drug_info = {
                    "available": False,
                    "status": None,
                    "job_id": q_ai_drug_job_id,
                    "raw": {"error": str(e.message)},
                }

        return {
            "project_id": project_id,
            "experiment_id": exp_id_str,
            "status": local_status,
            "progress": local_progress,
            "q_ai_drug": q_ai_drug_info,
            "updated_at": updated_at,
        }

    # ─── GNINA Logs ───────────────────────────────────────────────────────────

    async def get_gnina_logs(
        self,
        project_id: str,
        user_id: str,
        experiment_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> Tuple[List[dict], int]:
        await self._get_project_and_workspace(project_id, user_id)

        experiment = None
        if experiment_id:
            experiment = await experiment_repository.get_experiment_by_id_and_project(
                experiment_id, project_id
            )
            if not experiment or experiment.get("type") != "gnina":
                raise AppException(
                    status_code=404,
                    code="EXPERIMENT_NOT_FOUND",
                    message="GNINA experiment not found in this project",
                )
        else:
            items, _ = await experiment_repository.list_experiments(
                project_id=project_id,
                status=None,
                type="gnina",
                engine=None,
                skip=0,
                limit=1,
            )
            if items:
                experiment = items[0]

        if not experiment:
            return [], 0

        logs = experiment.get("logs", [])
        total = len(logs)
        page = logs[skip: skip + limit]

        # Attempt to merge q-ai-drug logs if job_id exists
        q_ai_drug_job_id = experiment.get("q_ai_drug_job_id")
        if q_ai_drug_job_id and skip == 0:
            try:
                raw_logs = await q_ai_drug_client.get_gnina_log(
                    params={"job_id": q_ai_drug_job_id}
                )
                if isinstance(raw_logs, list):
                    for entry in raw_logs:
                        page.append({
                            "timestamp": None,
                            "level": "info",
                            "message": str(entry),
                            "stage": "q_ai_drug",
                            "metadata": {"source": "q_ai_drug"},
                        })
                elif isinstance(raw_logs, dict) and "log" in raw_logs:
                    for line in str(raw_logs["log"]).splitlines():
                        if line.strip():
                            page.append({
                                "timestamp": None,
                                "level": "info",
                                "message": line.strip(),
                                "stage": "q_ai_drug",
                                "metadata": {"source": "q_ai_drug"},
                            })
            except QAiDrugClientError:
                pass  # q-ai-drug logs unavailable — return local logs only

        return page, total

    # ─── GNINA Results ────────────────────────────────────────────────────────

    async def list_gnina_results(
        self,
        project_id: str,
        user_id: str,
        experiment_id: Optional[str] = None,
        source_docking_experiment_id: Optional[str] = None,
        molecule_id: Optional[str] = None,
        target_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
        sort_by: str = "rank",
        sort_order: str = "asc",
    ) -> Tuple[List[dict], int]:
        await self._get_project_and_workspace(project_id, user_id)

        order = pymongo.ASCENDING if sort_order == "asc" else pymongo.DESCENDING

        await gnina_result_repository.ensure_indexes()
        items, total = await gnina_result_repository.list_results(
            project_id=project_id,
            experiment_id=experiment_id,
            source_docking_experiment_id=source_docking_experiment_id,
            molecule_id=molecule_id,
            target_id=target_id,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            sort_order=order,
        )
        return items, total

    # ─── GNINA Pose File ──────────────────────────────────────────────────────

    async def get_pose_file_metadata(
        self,
        project_id: str,
        pose_id: str,
        user_id: str,
    ) -> dict:
        project, workspace_id = await self._get_project_and_workspace(project_id, user_id)

        meta = await file_metadata_repository.get_metadata_by_file_id(pose_id)
        if not meta:
            raise AppException(
                status_code=404,
                code="GNINA_POSE_NOT_FOUND",
                message=f"GNINA pose file '{pose_id}' not found",
            )

        if str(meta.get("project_id")) != project_id:
            raise AppException(
                status_code=403,
                code="FILE_ACCESS_DENIED",
                message="Pose file does not belong to this project",
            )

        return meta


gnina_service = GninaService()
