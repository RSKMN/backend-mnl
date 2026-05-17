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
from app.repositories.target_repository import target_repository
from app.repositories.molecule_repository import molecule_repository
from app.repositories.project_input_repository import project_input_repository
from app.repositories.file_metadata_repository import file_metadata_repository
from app.repositories.docking_result_repository import docking_result_repository

logger = logging.getLogger("qudrugforge-docking-service")


class DockingService:
    # ─── Access Helpers ───────────────────────────────────────────────────────

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
        """Return (project, workspace_id) after validating existence and user access."""
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

    # ─── Create Docking Run ───────────────────────────────────────────────────

    async def create_docking_run(
        self,
        project_id: str,
        user_id: str,
        target_id: str,
        compound_selection: Dict[str, Any],
        engine: str,
        binding_site: Optional[Dict[str, Any]],
        parameters: Dict[str, Any],
        name: Optional[str] = None,
        simulate: bool = False,
    ) -> dict:
        """
        Validate inputs, create an experiment record of type 'docking', and return immediately.
        Heavy compute is NOT executed here — this is Phase 10 orchestration only.
        """
        project, workspace_id = await self._get_project_and_workspace(project_id, user_id)

        # 1. Validate target
        target = await target_repository.get_target_by_id(target_id)
        if not target:
            raise AppException(
                status_code=404,
                code="TARGET_NOT_FOUND",
                message=f"Target '{target_id}' not found",
            )
        if str(target.get("project_id")) != project_id:
            raise AppException(
                status_code=403,
                code="TARGET_NOT_IN_PROJECT",
                message="Target does not belong to this project",
            )

        target_gene = target.get("gene") or target.get("protein_name") or "unknown"

        # 2. Validate compound selection
        sel_mode = compound_selection.get("mode", "all")
        molecule_ids = compound_selection.get("molecule_ids", [])

        if sel_mode == "selected":
            if not molecule_ids:
                raise AppException(
                    status_code=400,
                    code="VALIDATION_ERROR",
                    message="molecule_ids must be provided and non-empty when mode is 'selected'",
                )
            # Verify each molecule belongs to this project
            invalid_ids = []
            for mid in molecule_ids:
                mol = await molecule_repository.get_molecule_by_id(mid)
                if not mol or str(mol.get("project_id")) != project_id:
                    invalid_ids.append(mid)
            if invalid_ids:
                raise AppException(
                    status_code=403,
                    code="MOLECULE_ACCESS_DENIED",
                    message=f"Molecules not found or not in this project: {invalid_ids}",
                )
            molecule_count = len(molecule_ids)
        elif sel_mode in ("all", "filtered"):
            molecule_count = await molecule_repository.count_by_project(project_id)
            if molecule_count == 0:
                raise AppException(
                    status_code=400,
                    code="INPUT_NOT_READY",
                    message="No molecules found in this project. Upload a compound library first.",
                )
        else:
            raise AppException(
                status_code=400,
                code="VALIDATION_ERROR",
                message="compound_selection.mode must be 'all', 'filtered', or 'selected'",
            )

        # 3. Resolve binding site (request > project_inputs fallback)
        resolved_binding_site = binding_site

        if not resolved_binding_site:
            proj_inputs = await project_input_repository.get_by_project_id(project_id)
            if proj_inputs:
                bs = proj_inputs.get("binding_site")
                if bs:
                    resolved_binding_site = bs

        if not resolved_binding_site:
            raise AppException(
                status_code=400,
                code="INPUT_NOT_READY",
                message=(
                    "No binding site configured. Provide binding_site in the request body "
                    "or configure it under project inputs first."
                ),
            )

        # 4. Build experiment name
        if not name:
            name = f"Docking Run — {target_gene} ({engine.upper()})"

        # 5. Create experiment document
        now = utc_now()
        exp_doc = {
            "workspace_id": ObjectId(workspace_id),
            "project_id": ObjectId(project_id),
            "name": name,
            "type": "docking",
            "engine": engine,
            "status": "queued",
            "progress": 0,
            "parameters": {
                "engine": engine,
                "target_id": target_id,
                "target_gene": target_gene,
                "compound_selection": compound_selection,
                "binding_site": resolved_binding_site,
                "docking_parameters": parameters,
                "molecule_count": molecule_count,
            },
            "input_file_ids": [],
            "output_file_ids": [],
            "logs": [
                {
                    "timestamp": now,
                    "level": "info",
                    "message": "Docking run queued",
                    "stage": "queued",
                    "metadata": {
                        "target_id": target_id,
                        "engine": engine,
                        "molecule_count": molecule_count,
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
            "target_gene": target_gene,
            "resolved_binding_site": resolved_binding_site,
            "simulate": simulate,
        }

    # ─── List Docking Runs ────────────────────────────────────────────────────

    async def list_docking_runs(
        self,
        project_id: str,
        user_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[dict], int]:
        """Return experiments of type=docking for this project."""
        project, workspace_id = await self._get_project_and_workspace(project_id, user_id)

        items, total = await experiment_repository.list_experiments(
            project_id=project_id,
            status=status,
            type="docking",
            engine=None,
            skip=skip,
            limit=limit,
        )
        return items, total

    # ─── Get Single Docking Run ───────────────────────────────────────────────

    async def get_docking_run(
        self,
        project_id: str,
        experiment_id: str,
        user_id: str,
    ) -> dict:
        """Return a single docking experiment, validating type=docking."""
        project, workspace_id = await self._get_project_and_workspace(project_id, user_id)

        experiment = await experiment_repository.get_experiment_by_id_and_project(
            experiment_id, project_id
        )
        if not experiment:
            raise AppException(
                status_code=404,
                code="EXPERIMENT_NOT_FOUND",
                message="Docking run not found in this project",
            )

        if experiment.get("type") != "docking":
            raise AppException(
                status_code=404,
                code="EXPERIMENT_NOT_FOUND",
                message="This experiment is not a docking run",
            )

        return experiment

    # ─── List Docking Results ─────────────────────────────────────────────────

    async def list_docking_results(
        self,
        project_id: str,
        user_id: str,
        experiment_id: Optional[str] = None,
        molecule_id: Optional[str] = None,
        target_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
        sort_by: str = "rank",
        sort_order: str = "asc",
    ) -> Tuple[List[dict], int]:
        """Fetch docking_results collection records for this project."""
        await self._get_project_and_workspace(project_id, user_id)

        order = pymongo.ASCENDING if sort_order == "asc" else pymongo.DESCENDING

        await docking_result_repository.ensure_indexes()
        items, total = await docking_result_repository.list_results(
            project_id=project_id,
            experiment_id=experiment_id,
            molecule_id=molecule_id,
            target_id=target_id,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            sort_order=order,
        )
        return items, total

    # ─── Resolve Pose File ────────────────────────────────────────────────────

    async def get_pose_file_metadata(
        self,
        project_id: str,
        pose_id: str,
        user_id: str,
    ) -> dict:
        """Resolve a pose_file_id to file metadata, validating project ownership."""
        project, workspace_id = await self._get_project_and_workspace(project_id, user_id)

        meta = await file_metadata_repository.get_metadata_by_file_id(pose_id)
        if not meta:
            raise AppException(
                status_code=404,
                code="FILE_NOT_FOUND",
                message=f"Pose file '{pose_id}' not found",
            )

        # Validate file belongs to this project
        if str(meta.get("project_id")) != project_id:
            raise AppException(
                status_code=403,
                code="FILE_ACCESS_DENIED",
                message="Pose file does not belong to this project",
            )

        return meta


docking_service = DockingService()
