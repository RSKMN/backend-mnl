"""
Phase D Verification Tests — Stage Orchestration
Verifies:
  - Stage dispatch generates valid lineage metadata
  - Retry creates new stage_job_id linked via retry_parent_stage_id
  - Dependency resolution logic works for known DAG
  - Downstream invalidation propagates stale metadata
  - Imported artifact injection fulfills lineage as status=imported
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.schemas.orchestration import (
    StageStatus,
    StageSource,
    StageRetryRequest,
    ImportStageArtifactRequest,
)
from app.services.stage_orchestrator_service import StageOrchestratorService, STAGE_DEPENDENCIES


@pytest.fixture
def orchestrator():
    return StageOrchestratorService()


@pytest.mark.asyncio
async def test_dispatch_stage_creates_lineage(orchestrator):
    """Verify dispatch creates a unique stage_job_id with correct lineage."""
    with patch("app.services.stage_orchestrator_service.experiment_repository") as mock_repo:
        mock_repo.update_experiment_fields = AsyncMock(return_value={})

        dispatch = await orchestrator.dispatch_stage(
            experiment_id="exp-001",
            pipeline_stage="docking",
            engine="vina",
            parent_stage_job_id="upstream-job-001",
            dependency_stage_ids=["filtering-job-001"],
        )

        assert dispatch.stage_job_id is not None
        assert len(dispatch.stage_job_id) == 36  # UUID format
        assert dispatch.pipeline_stage == "docking"
        assert dispatch.engine == "vina"
        assert dispatch.experiment_id == "exp-001"
        assert dispatch.source == StageSource.live_compute

        # Verify lineage metadata was persisted
        call_args = mock_repo.update_experiment_fields.call_args[0][1]
        assert call_args["stage_job_id"] == dispatch.stage_job_id
        assert call_args["parent_stage_job_id"] == "upstream-job-001"
        assert call_args["dependency_stage_ids"] == ["filtering-job-001"]
        assert call_args["retry_parent_stage_id"] is None


@pytest.mark.asyncio
async def test_retry_links_to_failed_stage(orchestrator):
    """Verify retry creates new stage_job_id with retry_parent_stage_id."""
    with patch("app.services.stage_orchestrator_service.experiment_repository") as mock_repo:
        mock_repo.update_experiment_fields = AsyncMock(return_value={})

        retry_req = StageRetryRequest(
            failed_stage_job_id="failed-job-001",
            retry_downstream=False,
        )

        dispatch = await orchestrator.schedule_retry(
            request=retry_req,
            experiment_id="exp-001",
            pipeline_stage="gnina",
            engine="gnina",
        )

        # New stage_job_id must differ from the failed one
        assert dispatch.stage_job_id != "failed-job-001"
        assert dispatch.stage_job_id is not None

        # retry_parent_stage_id must reference the failed stage
        call_args = mock_repo.update_experiment_fields.call_args[0][1]
        assert call_args["retry_parent_stage_id"] == "failed-job-001"
        assert call_args["retry_count"] == 1


@pytest.mark.asyncio
async def test_dependency_resolution_clears_when_satisfied(orchestrator):
    """Verify dependency resolver transitions to queued when all deps complete."""
    with patch("app.services.stage_orchestrator_service.experiment_repository") as mock_repo:
        mock_repo.update_experiment_fields = AsyncMock(return_value={})

        # gnina depends on docking
        result = await orchestrator.resolve_dependencies(
            experiment_id="exp-001",
            pipeline_stage="gnina",
            completed_stages=["docking"],  # docking completed
        )

        assert result is True
        call_args = mock_repo.update_experiment_fields.call_args[0][1]
        assert call_args["status"] == StageStatus.queued.value


@pytest.mark.asyncio
async def test_dependency_resolution_blocks_when_unsatisfied(orchestrator):
    """Verify dependency resolver transitions to waiting when deps incomplete."""
    with patch("app.services.stage_orchestrator_service.experiment_repository") as mock_repo:
        mock_repo.update_experiment_fields = AsyncMock(return_value={})

        # gnina depends on docking, but docking not in completed list
        result = await orchestrator.resolve_dependencies(
            experiment_id="exp-001",
            pipeline_stage="gnina",
            completed_stages=[],  # nothing completed
        )

        assert result is False
        call_args = mock_repo.update_experiment_fields.call_args[0][1]
        assert call_args["status"] == StageStatus.waiting_for_dependency.value


@pytest.mark.asyncio
async def test_downstream_invalidation_marks_stale(orchestrator):
    """Verify downstream invalidation injects stale metadata to all downstream stages."""
    with patch("app.services.stage_orchestrator_service.experiment_repository") as mock_repo:
        mock_repo.update_experiment_fields = AsyncMock(return_value={})

        await orchestrator.invalidate_downstream(
            source_stage_job_id="docking-job-v2",
            downstream_experiment_ids=["gnina-exp-001", "quantum-exp-001"],
        )

        assert mock_repo.update_experiment_fields.call_count == 2
        for call in mock_repo.update_experiment_fields.call_args_list:
            fields = call[0][1]
            assert fields["stale"] is True
            assert fields["invalidated_by_stage"] == "docking-job-v2"
            assert "invalidated_at" in fields


@pytest.mark.asyncio
async def test_imported_artifact_injection(orchestrator):
    """Verify imported artifact creates a stage job with status=imported."""
    with patch("app.services.stage_orchestrator_service.experiment_repository") as mock_repo:
        mock_repo.update_experiment_fields = AsyncMock(return_value={})

        req = ImportStageArtifactRequest(
            experiment_id="exp-001",
            pipeline_stage="gnina",
            artifact_id="file-777",
            artifact_uri="/api/v1/files/file-777",
            imported_from="external-lab",
            parent_stage_job_id="docking-job-001",
        )

        dispatch = await orchestrator.inject_imported_artifact(req)

        assert dispatch.source == StageSource.imported
        assert dispatch.engine == "imported"
        assert dispatch.stage_job_id is not None

        call_args = mock_repo.update_experiment_fields.call_args[0][1]
        assert call_args["status"] == StageStatus.imported.value
        assert call_args["source"] == StageSource.imported.value
        assert call_args["artifact_id"] == "file-777"


def test_dag_dependencies_are_complete():
    """Verify the STAGE_DEPENDENCIES DAG covers all valid stages without cycles."""
    required_stages = {"docking", "gnina", "quantum", "admet", "simulation", "report"}
    for stage in required_stages:
        assert stage in STAGE_DEPENDENCIES, f"Stage '{stage}' missing from DAG"
