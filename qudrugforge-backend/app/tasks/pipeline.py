import asyncio
import logging
from app.core.celery_app import celery_app
from app.services.pipeline_orchestrator_service import pipeline_orchestrator_service
from app.repositories.job_repository import job_repository

logger = logging.getLogger("qudrugforge-pipeline-task")

@celery_app.task(name="app.tasks.pipeline.run_pipeline_task", bind=True, max_retries=1)
def run_pipeline_task(self, pipeline_run_id: str, project_id: str, user_id: str, job_id: str):
    """
    Supervisor Celery Task.
    Runs the asyncio DAG polling loop to manage pipeline execution.
    """
    logger.info(f"Starting run_pipeline_task supervisor for pipeline {pipeline_run_id}")
    try:
        asyncio.run(pipeline_orchestrator_service.run_pipeline_supervisor(pipeline_run_id, project_id, user_id, job_id))
    except Exception as exc:
        logger.exception(f"Supervisor failed for pipeline {pipeline_run_id}")
        asyncio.run(job_repository.update_job_status(job_id, "FAILED", error_message=str(exc)))
        raise

@celery_app.task(name="app.tasks.pipeline.execute_engine_stage_task", bind=True, max_retries=3)
def execute_engine_stage_task(self, stage: str, exp_id: str, project_id: str, user_id: str, params: dict, pipeline_run_id: str, job_id: str):
    """
    Executes a single scientific engine stage.
    """
    logger.info(f"Executing stage {stage} for pipeline {pipeline_run_id}")
    try:
        result = asyncio.run(pipeline_orchestrator_service.execute_engine_stage_sync(
            stage, exp_id, project_id, user_id, params, pipeline_run_id, job_id
        ))
        
        # Return the arguments required by the chained import_artifacts_task
        # Note: the output of this task is passed as the first argument to the next task in the chain
        # but import_artifacts_task expects explicit kwargs. We can pass the required args via the chain signature directly,
        # but the result of this function might be fed as the first positional arg to import_artifacts_task.
        return result
    except Exception as exc:
        logger.exception(f"Stage {stage} failed")
        is_final_attempt = self.request.retries >= self.max_retries
        if is_final_attempt:
            asyncio.run(job_repository.update_job_status(job_id, "FAILED", error_message=str(exc)))
        else:
            from app.utils.datetime import utc_now
            from bson import ObjectId
            asyncio.run(job_repository.events_collection.insert_one({
                "job_id": ObjectId(job_id),
                "event_type": "TASK_RETRY",
                "previous_status": "RUNNING",
                "new_status": "RETRYING",
                "timestamp": utc_now(),
                "metadata": {
                    "retry_number": self.request.retries + 1,
                    "max_retries": self.max_retries,
                    "error_message": str(exc),
                    "timestamp": utc_now()
                }
            }))
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 5)
