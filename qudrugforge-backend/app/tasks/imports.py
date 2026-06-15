import asyncio
from app.core.celery_app import celery_app
from app.services.artifact_import_service import artifact_import_service
from app.repositories.job_repository import job_repository
import logging

logger = logging.getLogger("qudrugforge-import-task")

async def _run_import(job_id: str, project_id: str, user_id: str, run_name: str, experiment_id: str = None):
    # Transition to IMPORTING
    await job_repository.update_job_status(job_id, "IMPORTING", progress=80)
    try:
        result = await artifact_import_service.import_artifacts(
            project_id=project_id,
            user_id=user_id,
            run_name=run_name,
            experiment_id=experiment_id
        )
        # Transition to COMPLETED
        await job_repository.update_job_status(job_id, "COMPLETED", progress=100)
        # Update project's last_results_import_at timestamp
        from app.repositories.project_repository import project_repository
        from app.utils.datetime import utc_now
        await project_repository.update_project(project_id, {
            "last_results_import_at": utc_now()
        })
        return result
    except Exception as e:
        logger.exception(f"Import task failed for job {job_id}")
        raise

@celery_app.task(name="app.tasks.imports.import_artifacts_task", bind=True, max_retries=3)
def import_artifacts_task(self, job_id: str, project_id: str, user_id: str, run_name: str, experiment_id: str = None):
    """
    Celery task that executes the artifact import synchronously by wrapping the async call in asyncio.run().
    It is automatically routed to the 'imports' queue via celery_app config.
    """
    logger.info(f"Starting import_artifacts_task for job {job_id}, attempt {self.request.retries}")
    
    # asyncio.run creates a new event loop for this sync function call,
    # satisfying motor/mongodb async driver requirements.
    try:
        return asyncio.run(_run_import(job_id, project_id, user_id, run_name, experiment_id))
    except Exception as exc:
        is_final_attempt = self.request.retries >= self.max_retries
        if is_final_attempt:
            asyncio.run(job_repository.update_job_status(job_id, "FAILED", error_message=str(exc)))
        else:
            from app.utils.datetime import utc_now
            from bson import ObjectId
            asyncio.run(job_repository.events_collection.insert_one({
                "job_id": ObjectId(job_id),
                "event_type": "TASK_RETRY",
                "previous_status": "IMPORTING",
                "new_status": "RETRYING",
                "timestamp": utc_now(),
                "metadata": {
                    "retry_number": self.request.retries + 1,
                    "max_retries": self.max_retries,
                    "error_message": str(exc),
                    "timestamp": utc_now()
                }
            }))
        # Exponential backoff retry via Celery
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 5)
