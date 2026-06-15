import os
import shutil
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from bson import ObjectId
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.core.exceptions import AppException
from app.utils.datetime import utc_now
from app.repositories.pipeline_repository import pipeline_repository
from app.repositories.experiment_repository import experiment_repository
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.services.artifact_import_service import artifact_import_service
from app.integrations.q_ai_drug_execution import q_ai_drug_execution_service
from app.services.stage_orchestrator_service import stage_orchestrator_service
from app.repositories.job_repository import job_repository
from app.services.audit_service import audit_service
from app.services.usage_service import usage_service

logger = logging.getLogger("qudrugforge-pipeline-orchestrator")

VALID_STAGES = {
    "target_ranking",
    "molecule_generation",
    "filtering",
    "docking",
    "gnina",
    "quantum",
    "admet",
    "simulation",
    "report"
}

STAGE_ENGINES = {
    "target_ranking": "q_ai_drug",
    "molecule_generation": "q_ai_drug",
    "filtering": "q_ai_drug",
    "docking": "vina",
    "gnina": "gnina",
    "quantum": "quantum",
    "admet": "admet",
    "simulation": "md",
    "report": "internal"
}

class PipelineOrchestratorService:
    def validate_pipeline_stages(self, pipeline: List[str]):
        """
        Validates that all specified stages in the pipeline list are supported.
        Raises an AppException with INVALID_PIPELINE_STAGE code if invalid.
        """
        for stage in pipeline:
            if stage not in VALID_STAGES:
                raise AppException(
                    status_code=400,
                    code="INVALID_PIPELINE_STAGE",
                    message=f"Pipeline stage '{stage}' is not recognized or supported. Valid stages: {list(VALID_STAGES)}"
                )

    async def create_pipeline_run(
        self,
        project_id: str,
        workspace_id: str,
        pipeline: List[str],
        parameters: Dict[str, Any],
        user_id: str
    ) -> dict:
        """
        Creates a new pipeline run document in the database with queued stages.
        """
        # Service-layer RBAC check
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(status_code=403, code="WORKSPACE_ACCESS_DENIED", message="Not a workspace member")
        role = membership.get("role", "viewer").upper()
        if role != "OWNER" and role not in ["ADMIN", "SCIENTIST"]:
            raise AppException(status_code=403, code="WORKSPACE_ACCESS_DENIED", message="ADMIN or SCIENTIST role required")

        self.validate_pipeline_stages(pipeline)
        
        now = utc_now()
        stage_statuses = {}
        for stage in pipeline:
            stage_statuses[stage] = {
                "status": "queued",
                "progress": 0,
                "started_at": None,
                "completed_at": None,
                "experiment_id": None,
                "output_artifact_ids": [],
                "error": None
            }

        doc = {
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(workspace_id),
            "status": "queued",
            "pipeline": pipeline,
            "parameters": parameters,
            "stage_statuses": stage_statuses,
            "created_by": ObjectId(user_id),
            "created_at": now,
            "updated_at": now
        }
        
        await pipeline_repository.ensure_indexes()
        return await pipeline_repository.create_pipeline_run(doc)

    async def run_pipeline_supervisor(self, pipeline_run_id: str, project_id: str, user_id: str, supervisor_job_id: str):
        """
        Supervisor DAG executor loop running inside a Celery task.
        Dispatches heavy stages via Celery chain and polls for completion.
        """
        logger.info(f"Starting Celery Supervisor DAG execution of pipeline run '{pipeline_run_id}' for project '{project_id}'")
        
        await job_repository.update_job_status(supervisor_job_id, "RUNNING", progress=5)

        # Ensure fallback data is copied to the correct outputs root to support self-healing import.
        self._ensure_sample_outputs_available()

        pipeline_run = await pipeline_repository.get_pipeline_run_by_id(pipeline_run_id)
        if not pipeline_run:
            logger.error(f"Pipeline run '{pipeline_run_id}' not found. Aborting execution.")
            await job_repository.update_job_status(supervisor_job_id, "FAILED", error_message="Pipeline run not found.")
            return

        workspace_id = str(pipeline_run["workspace_id"])
        stages = pipeline_run["pipeline"]
        parameters = pipeline_run.get("parameters", {})

        # Transition overall pipeline status to "running"
        await pipeline_repository.update_pipeline_status(pipeline_run_id, "running")
        await project_repository.update_project(project_id, {
            "status": "active",
            "last_pipeline_run_at": utc_now()
        })
        
        # Priority 1: Map Backend Inputs to Executor
        from app.services.project_input_service import project_input_service
        from app.services.file_service import file_service
        try:
            inputs_doc = await project_input_service.get_project_inputs(project_id, user_id)
            dynamic_inputs = {}
            if inputs_doc:
                if "binding_site" in inputs_doc:
                    dynamic_inputs["binding_site"] = inputs_doc["binding_site"]
                
                # Resolve physical paths
                for key in ["protein_fasta_file_id", "protein_structure_file_id", "alphafold_structure_file_id", "reference_ligand_file_id", "assay_data_file_id"]:
                    file_id = inputs_doc.get(key)
                    if file_id:
                        try:
                            path, _ = await file_service.get_file_download_path(file_id, user_id)
                            dynamic_inputs[key.replace("_file_id", "_path")] = path
                        except Exception as e:
                            logger.warning(f"Failed to resolve physical path for {key}={file_id}: {e}")
            
            parameters["dynamic_inputs"] = dynamic_inputs
            
            # Inject GCS output URI for the engine to upload artifacts back
            if settings.STORAGE_PROVIDER == "gcs":
                # Provide a structured URI for the engine outputs
                gcs_uri = f"gs://{settings.GCS_BUCKET_NAME}/runs/{workspace_id}/{project_id}/{pipeline_run_id}"
                parameters["dynamic_inputs"]["gcs_output_uri"] = gcs_uri
            
            logger.info(f"Resolved dynamic inputs for project {project_id}: {dynamic_inputs}")
        except Exception as e:
            logger.error(f"Failed to resolve dynamic inputs: {e}")
            parameters["dynamic_inputs"] = {}

        # 1. Create all stage Experiments in MongoDB upfront
        stage_to_exp_id = {}
        for idx, stage in enumerate(stages):
            now = utc_now()
            experiment_type = "molecule_filtering" if stage == "filtering" else stage
            
            exp_doc = {
                "workspace_id": ObjectId(workspace_id),
                "project_id": ObjectId(project_id),
                "name": f"{stage.replace('_', ' ').title()} Stage — Run {pipeline_run_id[:8]}",
                "type": experiment_type,
                "engine": STAGE_ENGINES.get(stage, "other"),
                "status": "waiting_for_dependency",
                "progress": 0,
                "parameters": {**parameters.get(stage, {}), "dynamic_inputs": parameters.get("dynamic_inputs", {})},
                "input_file_ids": [],
                "output_file_ids": [],
                "logs": [],
                "parent_pipeline_run_id": ObjectId(pipeline_run_id),
                "metadata": {
                    "stage_sequence_index": idx,
                    "parent_pipeline_run_id": ObjectId(pipeline_run_id)
                },
                "created_by": ObjectId(user_id),
                "created_at": now,
                "updated_at": now
            }
            
            created_exp = await experiment_repository.create_experiment(exp_doc)
            stage_to_exp_id[stage] = str(created_exp["_id"])

            # Link pipeline status experiment ID
            stage_status = {
                "status": "queued",
                "progress": 0,
                "experiment_id": stage_to_exp_id[stage]
            }
            await pipeline_repository.update_stage_status(pipeline_run_id, stage, stage_status)

        # 2. Setup Loop Variables
        completed_stages = set()
        failed_stages = set()
        running_stages = {}  # stage_name -> stage_job_id
        
        # We don't need a semaphore here because Celery workers enforce concurrency dynamically.
        # But we can limit in-flight dispatches if needed. For now, dispatch all ready tasks.

        # 3. Execution Supervisor Loop (Polling Transitional Implementation)
        while len(completed_stages) + len(failed_stages) < len(stages):
            # Check pipeline level failure/cancellation
            current_run = await pipeline_repository.get_pipeline_run_by_id(pipeline_run_id)
            if current_run and current_run.get("status") in ("cancelled", "failed"):
                logger.warning(f"Pipeline run '{pipeline_run_id}' was cancelled or marked failed. Stopping execution loop.")
                break

            if failed_stages:
                break

            # Poll running stages
            new_running = {}
            for stage, stage_job_id in running_stages.items():
                job_doc = await job_repository.get_job_by_id(stage_job_id)
                if not job_doc:
                    new_running[stage] = stage_job_id
                    continue
                
                status = job_doc.get("status")
                if status == "COMPLETED":
                    completed_stages.add(stage)
                    # Update pipeline progress based on completed stages
                    progress_val = int(((len(completed_stages)) / len(stages)) * 90) + 5
                    await job_repository.update_job_status(supervisor_job_id, "RUNNING", progress=progress_val)
                    
                    compute_seconds = job_doc.get("compute_seconds", 0)
                    if compute_seconds > 0:
                        asyncio.create_task(
                            usage_service.record_compute(
                                project_id=project_id,
                                workspace_id=workspace_id,
                                user_id=user_id,
                                compute_seconds=compute_seconds,
                                metadata={"stage": stage, "job_id": stage_job_id}
                            )
                        )
                    
                    stage_status = {
                        "status": "completed",
                        "progress": 100,
                        "completed_at": utc_now(),
                    }
                    await pipeline_repository.update_stage_status(pipeline_run_id, stage, stage_status)
                elif status in ["FAILED", "CANCELLED"]:
                    failed_stages.add(stage)
                    stage_status = {
                        "status": "failed",
                        "progress": 50,
                        "completed_at": utc_now(),
                        "error": job_doc.get("error_message", "Unknown error")
                    }
                    await pipeline_repository.update_stage_status(pipeline_run_id, stage, stage_status)
                else:
                    new_running[stage] = stage_job_id
            
            running_stages = new_running

            # If any stage failed, abort
            if failed_stages:
                break

            ready_stages = []
            for stage in stages:
                if stage in completed_stages or stage in running_stages or stage in failed_stages:
                    continue
                
                exp_id = stage_to_exp_id[stage]
                is_ready = await stage_orchestrator_service.resolve_dependencies(
                    experiment_id=exp_id,
                    pipeline_stage=stage,
                    completed_stages=list(completed_stages),
                    active_pipeline_stages=stages
                )
                if is_ready:
                    ready_stages.append(stage)

            # Dispatch ready stages via Celery Chain
            for stage in ready_stages:
                exp_id = stage_to_exp_id[stage]
                stage_job_id = await self._dispatch_stage_chain(stage, exp_id, project_id, user_id, parameters, pipeline_run_id)
                running_stages[stage] = stage_job_id
                
                stage_status = {
                    "status": "running",
                    "progress": 10,
                    "started_at": utc_now(),
                }
                await pipeline_repository.update_stage_status(pipeline_run_id, stage, stage_status)

            if not running_stages:
                if len(completed_stages) + len(failed_stages) < len(stages):
                    logger.error("Pipeline DAG deadlock detected. No stages ready and no tasks running.")
                    failed_stages.add("deadlock")
                    break
                else:
                    break

            # Sleep briefly to avoid aggressive polling
            await asyncio.sleep(settings.TESTING_POLL_INTERVAL)

        # 4. Final Cleanup
        if failed_stages or (current_run and current_run.get("status") in ("cancelled", "failed")):
            await pipeline_repository.update_pipeline_status(pipeline_run_id, "failed")
            await job_repository.update_job_status(supervisor_job_id, "FAILED", error_message="Pipeline execution failed.")
            # Cancel remaining stages
            remaining = [s for s in stages if s not in completed_stages and s not in failed_stages and s not in running_stages]
            await self._cancel_remaining_stages(pipeline_run_id, remaining, stage_to_exp_id)
            asyncio.create_task(
                audit_service.log_event(
                    action="PIPELINE_FAILED",
                    user_id=user_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    metadata={"pipeline_run_id": pipeline_run_id}
                )
            )
        else:
            await pipeline_repository.update_pipeline_status(pipeline_run_id, "completed")
            await project_repository.update_project(project_id, {
                "status": "completed"
            })
            await job_repository.update_job_status(supervisor_job_id, "COMPLETED", progress=100)
            asyncio.create_task(
                audit_service.log_event(
                    action="PIPELINE_EXECUTED",
                    user_id=user_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    metadata={"pipeline_run_id": pipeline_run_id}
                )
            )
    async def _cancel_remaining_stages(self, pipeline_run_id: str, remaining_stages: List[str], stage_to_exp_id: Dict[str, str]):
        for stage in remaining_stages:
            stage_status = {
                "status": "failed",
                "progress": 0,
                "completed_at": utc_now(),
                "error": "Pipeline aborted due to upstream failure."
            }
            await pipeline_repository.update_stage_status(pipeline_run_id, stage, stage_status)
            
            exp_id = stage_to_exp_id.get(stage)
            if exp_id:
                await experiment_repository.update_experiment_fields(exp_id, {
                    "status": "failed",
                    "error": "Pipeline aborted due to upstream failure.",
                    "updated_at": utc_now()
                })

    async def _dispatch_stage_chain(self, stage: str, exp_id: str, project_id: str, user_id: str, params: dict, pipeline_run_id: str) -> str:
        """
        Creates a Job document and dispatches the Celery Chain: Execute -> Import
        Returns the stage_job_id so the supervisor can poll its completion.
        """
        job_doc = {
            "project_id": ObjectId(project_id),
            "experiment_id": ObjectId(exp_id),
            "task_type": f"stage_{stage}",
            "status": "QUEUED",
            "progress": 0,
            "created_at": utc_now()
        }
        job = await job_repository.create_job(job_doc)
        stage_job_id = str(job["_id"])
        
        if settings.ENABLE_DEV_JOB_SIMULATION:
            async def simulated_chain():
                try:
                    await job_repository.update_job_status(stage_job_id, "RUNNING", progress=10)
                    await asyncio.sleep(2)
                    
                    # Update experiment to importing results state
                    await experiment_repository.update_status_progress(exp_id, "importing_results", 80)
                    
                    await artifact_import_service.import_artifacts(project_id, user_id, "cancer_proof_v1", exp_id)
                    
                    await stage_orchestrator_service.mark_stage_completed(exp_id, stage_job_id, stage, [])
                    await job_repository.update_job_status(stage_job_id, "COMPLETED", progress=100)
                except Exception as e:
                    logger.exception(f"Simulated chain failed for {stage}")
                    await job_repository.update_job_status(stage_job_id, "FAILED", error_message=str(e))
            
            asyncio.create_task(simulated_chain())
        else:
            # Synchronous testing
            output_dir = await self.execute_engine_stage_sync(stage, exp_id, project_id, user_id, params, pipeline_run_id, stage_job_id)
            await artifact_import_service.import_artifacts(project_id, user_id, output_dir, exp_id)
            await job_repository.update_job_status(stage_job_id, "COMPLETED", progress=100)
        
        return stage_job_id

    async def execute_engine_stage_sync(self, stage: str, exp_id: str, project_id: str, user_id: str, params: dict, pipeline_run_id: str, job_id: str):
        """
        Synchronous-wrapped execution logic for the specific engine stage, called by the Celery worker.
        """
        await job_repository.update_job_status(job_id, "RUNNING", progress=10)
        
        engine = STAGE_ENGINES.get(stage, "other")
        stage_params = {**params.get(stage, {}), "dynamic_inputs": params.get("dynamic_inputs", {})}

        # Copy intermediate files from other completed stages of this pipeline run
        try:
            pipeline_run = await pipeline_repository.get_pipeline_run_by_id(pipeline_run_id)
            if pipeline_run:
                stage_statuses = pipeline_run.get("stage_statuses", {})
                current_stage_dir = Path(settings.Q_AI_DRUG_OUTPUT_ROOT) / "runs" / exp_id
                current_stage_dir.mkdir(parents=True, exist_ok=True)
                
                for sibling_stage, info in stage_statuses.items():
                    if info.get("status") == "completed" and info.get("experiment_id"):
                        sibling_exp_id = str(info["experiment_id"])
                        sibling_dir = Path(settings.Q_AI_DRUG_OUTPUT_ROOT) / "runs" / sibling_exp_id
                        if sibling_dir.exists() and sibling_dir.is_dir() and sibling_exp_id != exp_id:
                            logger.info(f"Copying intermediate artifacts from completed sibling stage '{sibling_stage}' ({sibling_dir}) to current stage '{stage}' ({current_stage_dir})...")
                            for root, dirs, files in os.walk(sibling_dir):
                                rel_root = Path(root).relative_to(sibling_dir)
                                dest_dir = current_stage_dir / rel_root
                                dest_dir.mkdir(parents=True, exist_ok=True)
                                for f in files:
                                    if f in ("status.json", "run_log.jsonl", f"{sibling_stage}_summary.json"):
                                        continue
                                    shutil.copy2(Path(root) / f, dest_dir / f)
        except Exception as copy_err:
            logger.warning(f"Failed to copy intermediate files between stages: {copy_err}")

        dispatch_req = await stage_orchestrator_service.dispatch_stage(
            experiment_id=exp_id,
            pipeline_stage=stage,
            engine=engine,
            parameters=stage_params
        )

        try:
            res = await q_ai_drug_execution_service.execute_stage(dispatch_req)

            for log_line in res.get("logs", []):
                await experiment_repository.append_log(exp_id, {
                    "timestamp": utc_now(),
                    "level": "info",
                    "message": f"[q-ai-drug stdout] {log_line}",
                    "stage": stage,
                    "metadata": {}
                })
                await job_repository.logs_collection.insert_one({
                    "job_id": ObjectId(job_id),
                    "level": "info",
                    "message": f"[{stage}] {log_line}",
                    "timestamp": utc_now()
                })

            await experiment_repository.update_status_progress(exp_id, "importing_results", 80)
            
            output_dir = res.get("output_dir")
            if not output_dir or not Path(output_dir).exists():
                raise AppException(status_code=500, code="MISSING_ARTIFACT", message="Output directory missing after execution.")

            await stage_orchestrator_service.mark_stage_completed(
                experiment_id=exp_id,
                stage_job_id=dispatch_req.stage_job_id,
                pipeline_stage=stage,
                output_artifact_ids=[]
            )
            
            # Note: We do NOT transition to COMPLETED here. The import_artifacts_task in the chain will do that.
            return output_dir

        except Exception as exc:
            logger.exception(f"Pipeline stage '{stage}' failed: {str(exc)}")
            err_msg = getattr(exc, "message", str(exc))
            
            await stage_orchestrator_service.mark_stage_failed(
                experiment_id=exp_id,
                stage_job_id=dispatch_req.stage_job_id,
                pipeline_stage=stage,
                error=err_msg
            )
            raise

    # ─── Fallback Helper ──────────────────────────────────────────────────────

    def _ensure_sample_outputs_available(self):
        """
        Self-healing data mechanism. Copies high fidelity oncology outputs 
        from 'tests/utils/sample_q_ai_drug_outputs' into the real 
        'Q_AI_DRUG_OUTPUT_ROOT' folder to enable instant, zero-setup runs.
        """
        try:
            target_root = Path(settings.Q_AI_DRUG_OUTPUT_ROOT).resolve()
            target_dir = target_root / "cancer_proof_v1"
            
            if target_dir.exists() and any(target_dir.iterdir()):
                return
                
            # Locate sample data in workspace tests
            source_dir = Path(__file__).parent.parent / "tests" / "utils" / "sample_q_ai_drug_outputs" / "cancer_proof_v1"
            if not source_dir.exists():
                source_dir = Path("./tests/utils/sample_q_ai_drug_outputs/cancer_proof_v1").resolve()
                
            if source_dir.exists() and source_dir.is_dir():
                logger.info(f"Self-healing: Copying high-fidelity oncology outputs from '{source_dir}' to '{target_dir}'...")
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
                logger.info("Self-healing copy completed successfully.")
        except Exception as e:
            logger.warning(f"Self-healing copy failed: {str(e)}. Continuing with standard resolution.")

pipeline_orchestrator_service = PipelineOrchestratorService()
