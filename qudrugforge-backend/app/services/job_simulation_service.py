import asyncio
import logging
from app.repositories.experiment_repository import experiment_repository
from app.core.config import settings
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-job-simulation")

async def run_experiment_simulation(experiment_id: str):
    """
    Simulates a development workflow lifecycle for an experiment/job by updating
    its status, progress, and appending logs over time without blocking the API.
    """
    if not settings.ENABLE_DEV_JOB_SIMULATION:
        logger.warning("Job simulation is disabled by configuration settings.")
        return

    step_delay = settings.JOB_SIMULATION_STEP_SECONDS
    
    async def push_log(message: str, stage: str, level: str = "info"):
        log_item = {
            "timestamp": utc_now(),
            "level": level,
            "message": message,
            "stage": stage,
            "metadata": {}
        }
        await experiment_repository.append_log(experiment_id, log_item)

    try:
        # Step 1: Initialization & Running (10% Progress)
        await asyncio.sleep(step_delay)
        await experiment_repository.update_status_progress(
            experiment_id=experiment_id,
            status="running",
            progress=10,
            started_at=utc_now()
        )
        await push_log("Experiment started and initializing environment resources", stage="initialization")

        # Step 2: Input validation (30% Progress)
        await asyncio.sleep(step_delay)
        await experiment_repository.update_status_progress(
            experiment_id=experiment_id,
            status="running",
            progress=30
        )
        await push_log("Input validation completed successfully. Structure and ligands verified", stage="validation")

        # Step 3: Scientific processing (60% Progress)
        await asyncio.sleep(step_delay)
        await experiment_repository.update_status_progress(
            experiment_id=experiment_id,
            status="running",
            progress=60
        )
        await push_log("Core processing stage completed. Binding energy metrics computed", stage="processing")

        # Step 4: Finalizing outputs (90% Progress)
        await asyncio.sleep(step_delay)
        await experiment_repository.update_status_progress(
            experiment_id=experiment_id,
            status="running",
            progress=90
        )
        await push_log("Finalizing outputs and preparing structural reports", stage="finalization")

        # Step 5: Completed (100% Progress)
        await asyncio.sleep(step_delay)
        await experiment_repository.update_status_progress(
            experiment_id=experiment_id,
            status="completed",
            progress=100,
            completed_at=utc_now()
        )
        await push_log("Experiment completed successfully. All poses stored and indexed", stage="completion")

    except Exception as e:
        logger.error(f"Job simulation for experiment '{experiment_id}' failed: {str(e)}")
        # If simulation fails or is cancelled, mark it failed to preserve UI integrity
        try:
            await experiment_repository.update_status_progress(
                experiment_id=experiment_id,
                status="failed",
                progress=50,
                error=f"Simulation error: {str(e)}"
            )
            await push_log(f"Simulation failed unexpectedly: {str(e)}", stage="error", level="error")
        except Exception:
            pass
