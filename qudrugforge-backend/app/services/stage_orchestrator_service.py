"""
Phase D — Stage Orchestrator Service
backend-mnl's core orchestration engine.

This service replaces monolithic run_pipeline() assumptions with
granular, dependency-aware, retry-safe stage orchestration.

Responsibilities:
- Stage dispatch (queued → running)
- Dependency resolution (waiting_for_dependency → queued)
- Failure propagation (failed → downstream cancelled/stale)
- Downstream invalidation (stale marking)
- Retry scheduling (new stage_job_id, retry_parent_stage_id)
- Imported artifact participation in lineage
- Real-time orchestration event emission
"""
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from app.utils.datetime import utc_now
from app.repositories.experiment_repository import experiment_repository
from app.schemas.orchestration import (
    StageJob,
    StageLineage,
    StageStatus,
    StageSource,
    StaleMetadata,
    OrchestrationEvent,
    OrchestrationEventType,
    StageDispatchRequest,
    StageRetryRequest,
    ImportStageArtifactRequest,
    StageStatusItem,
    ExperimentOrchestrationStatus,
)

logger = logging.getLogger("qudrugforge-stage-orchestrator")

# Event sequence counter per experiment (in-memory; Phase E should persist this)
_event_sequence_counters: Dict[str, int] = {}

# ─── DAG: Stage dependency map ────────────────────────────────────────────────
# Defines which stages must complete before each stage can begin.
STAGE_DEPENDENCIES: Dict[str, List[str]] = {
    "target_ranking":     [],
    "molecule_generation": ["target_ranking"],
    "filtering":          ["molecule_generation"],
    "docking":            ["filtering"],
    "gnina":              ["docking"],
    "quantum":            ["gnina"],
    "admet":              ["filtering"],
    "simulation":         ["gnina"],
    "report":             ["docking", "gnina", "quantum", "admet", "simulation"],
}


class StageOrchestratorService:
    """
    backend-mnl's Stage Orchestrator.

    This is the single authority for:
    - Stage lifecycle transitions
    - Dependency graph evaluation
    - Downstream invalidation
    - Retry scheduling
    - Imported artifact injection
    """

    # ─── Stage Dispatch ───────────────────────────────────────────────────────

    async def dispatch_stage(
        self,
        experiment_id: str,
        pipeline_stage: str,
        engine: str,
        parent_stage_job_id: Optional[str] = None,
        dependency_stage_ids: Optional[List[str]] = None,
        retry_parent_stage_id: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> StageDispatchRequest:
        """
        Creates a new StageJob with a fresh stage_job_id and attaches
        its lineage metadata before dispatching to the execution interface.
        """
        stage_job_id = str(uuid.uuid4())

        lineage = StageLineage(
            experiment_id=experiment_id,
            stage_job_id=stage_job_id,
            pipeline_stage=pipeline_stage,
            parent_stage_job_id=parent_stage_job_id,
            dependency_stage_ids=dependency_stage_ids or [],
            retry_parent_stage_id=retry_parent_stage_id,
        )

        dispatch = StageDispatchRequest(
            stage_job_id=stage_job_id,
            experiment_id=experiment_id,
            pipeline_stage=pipeline_stage,
            dependency_stage_ids=dependency_stage_ids or [],
            retry_parent_stage_id=retry_parent_stage_id,
            engine=engine,
            parameters=parameters or {},
            source=StageSource.live_compute,
        )

        logger.info(
            f"[DISPATCH] stage={pipeline_stage} stage_job_id={stage_job_id} "
            f"experiment_id={experiment_id} retry_of={retry_parent_stage_id}"
        )

        # Persist lineage metadata into the Experiment document
        await experiment_repository.update_experiment_fields(experiment_id, {
            "stage_job_id": stage_job_id,
            "parent_stage_job_id": parent_stage_job_id,
            "dependency_stage_ids": dependency_stage_ids or [],
            "retry_parent_stage_id": retry_parent_stage_id,
            "retry_count": 0 if not retry_parent_stage_id else 1,
            "stage_started_at": utc_now(),
            "stale": False,
            "updated_at": utc_now(),
        })

        await self._emit_event(OrchestrationEventType.stage_started, experiment_id, stage_job_id, pipeline_stage)
        return dispatch

    # ─── Dependency Resolver ──────────────────────────────────────────────────

    async def resolve_dependencies(
        self,
        experiment_id: str,
        pipeline_stage: str,
        completed_stages: List[str],
        active_pipeline_stages: Optional[List[str]] = None
    ) -> bool:
        """
        Evaluates whether all dependencies for a stage have been satisfied.
        Returns True if the stage is cleared for dispatch.
        Emits dependency_resolved event if all cleared.
        """
        required = STAGE_DEPENDENCIES.get(pipeline_stage, [])
        if active_pipeline_stages is not None:
            required = [dep for dep in required if dep in active_pipeline_stages]

        if not required:
            return True  # No dependencies → immediately dispatchable

        satisfied = all(dep in completed_stages for dep in required)

        if satisfied:
            logger.info(f"[DEPENDENCY_RESOLVED] stage={pipeline_stage} experiment={experiment_id}")
            await experiment_repository.update_experiment_fields(experiment_id, {
                "status": StageStatus.queued.value,
                "updated_at": utc_now(),
            })
            await self._emit_event(OrchestrationEventType.dependency_resolved, experiment_id, "", pipeline_stage)
        else:
            logger.info(f"[WAITING_DEPENDENCY] stage={pipeline_stage} experiment={experiment_id}")
            await experiment_repository.update_experiment_fields(experiment_id, {
                "status": StageStatus.waiting_for_dependency.value,
                "updated_at": utc_now(),
            })

        return satisfied

    # ─── Stage Completion ─────────────────────────────────────────────────────

    async def mark_stage_completed(
        self,
        experiment_id: str,
        stage_job_id: str,
        pipeline_stage: str,
        output_artifact_ids: Optional[List[str]] = None,
    ):
        """
        Transitions a stage to completed and emits the completion event.
        """
        await experiment_repository.update_experiment_fields(experiment_id, {
            "status": StageStatus.completed.value,
            "stage_job_id": stage_job_id,
            "stage_completed_at": utc_now(),
            "output_file_ids": output_artifact_ids or [],
            "stale": False,
            "updated_at": utc_now(),
        })
        await self._emit_event(OrchestrationEventType.stage_completed, experiment_id, stage_job_id, pipeline_stage)
        logger.info(f"[COMPLETED] stage={pipeline_stage} stage_job_id={stage_job_id}")

    # ─── Failure Propagation ──────────────────────────────────────────────────

    async def mark_stage_failed(
        self,
        experiment_id: str,
        stage_job_id: str,
        pipeline_stage: str,
        error: str,
        downstream_experiment_ids: Optional[List[str]] = None,
    ):
        """
        Marks a stage as failed, propagates dependency_failure to direct
        downstream stages, and marks them stale.
        """
        await experiment_repository.update_experiment_fields(experiment_id, {
            "status": StageStatus.failed.value,
            "stage_completed_at": utc_now(),
            "error": error,
            "updated_at": utc_now(),
        })
        await self._emit_event(OrchestrationEventType.stage_failed, experiment_id, stage_job_id, pipeline_stage,
                               payload={"error": error})

        # Propagate dependency failure downstream
        if downstream_experiment_ids:
            await self._invalidate_downstream(
                source_stage_job_id=stage_job_id,
                downstream_experiment_ids=downstream_experiment_ids,
                dependency_failure=True,
            )

    # ─── Downstream Invalidation ──────────────────────────────────────────────

    async def invalidate_downstream(
        self,
        source_stage_job_id: str,
        downstream_experiment_ids: List[str],
    ):
        """
        Public method to mark downstream stages stale when upstream recomputes.
        """
        await self._invalidate_downstream(source_stage_job_id, downstream_experiment_ids)

    async def _invalidate_downstream(
        self,
        source_stage_job_id: str,
        downstream_experiment_ids: List[str],
        dependency_failure: bool = False,
        invalidation_reason: Optional[str] = None,
    ):
        now = utc_now()
        # Canonical reason defaulting
        if invalidation_reason is None:
            invalidation_reason = "upstream_failed" if dependency_failure else "upstream_recomputed"
        for exp_id in downstream_experiment_ids:
            update = {
                "stale": True,
                "invalidated_by_stage": source_stage_job_id,
                "invalidated_at": now,
                "invalidation_reason": invalidation_reason,
                "updated_at": now,
            }
            if dependency_failure:
                update["dependency_failure"] = True
                update["status"] = StageStatus.cancelled.value
            await experiment_repository.update_experiment_fields(exp_id, update)
            logger.info(
                f"[INVALIDATED] experiment={exp_id} by_stage={source_stage_job_id} "
                f"reason={invalidation_reason} dep_failure={dependency_failure}"
            )
        await self._emit_event(
            OrchestrationEventType.downstream_invalidated,
            downstream_experiment_ids[0] if downstream_experiment_ids else "",
            source_stage_job_id,
            "downstream",
            payload={"count": len(downstream_experiment_ids), "dependency_failure": dependency_failure,
                     "invalidation_reason": invalidation_reason},
        )

    # ─── Retry Scheduling ─────────────────────────────────────────────────────

    async def schedule_retry(
        self,
        request: StageRetryRequest,
        experiment_id: str,
        pipeline_stage: str,
        engine: str,
        parameters: Optional[Dict[str, Any]] = None,
        downstream_experiment_ids: Optional[List[str]] = None,
    ) -> StageDispatchRequest:
        """
        Issues a retry for a failed stage.
        - Generates a new stage_job_id.
        - Links retry_parent_stage_id to the failed attempt.
        - Optionally re-schedules downstream stale stages.
        """
        logger.info(f"[RETRY] Scheduling retry for failed_stage={request.failed_stage_job_id}")

        await self._emit_event(
            OrchestrationEventType.retry_started,
            experiment_id,
            request.failed_stage_job_id,
            pipeline_stage,
        )

        dispatch = await self.dispatch_stage(
            experiment_id=experiment_id,
            pipeline_stage=pipeline_stage,
            engine=engine,
            retry_parent_stage_id=request.failed_stage_job_id,
            parameters=parameters,
        )

        if request.retry_downstream and downstream_experiment_ids:
            logger.info(f"[RETRY_DOWNSTREAM] Rescheduling {len(downstream_experiment_ids)} downstream stages.")
            for downstream_exp_id in downstream_experiment_ids:
                await experiment_repository.update_experiment_fields(downstream_exp_id, {
                    "status": StageStatus.queued.value,
                    "stale": False,
                    "invalidated_by_stage": None,
                    "invalidated_at": None,
                    "updated_at": utc_now(),
                })

        return dispatch

    # ─── Imported Artifact Injection ──────────────────────────────────────────

    async def inject_imported_artifact(
        self,
        request: ImportStageArtifactRequest,
        parent_artifact_id: Optional[str] = None,
    ) -> StageDispatchRequest:
        """
        Creates a StageJob record for a manually imported artifact,
        allowing it to participate in the lineage graph and satisfy
        downstream dependencies.
        Phase D Hardening: parent_artifact_id chains immutable artifact lineage.
        """
        stage_job_id = str(uuid.uuid4())
        now = utc_now()

        await experiment_repository.update_experiment_fields(request.experiment_id, {
            "status": StageStatus.imported.value,
            "source": StageSource.imported.value,
            "stage_job_id": stage_job_id,
            "parent_stage_job_id": request.parent_stage_job_id,
            "imported_from_stage_id": request.artifact_id,
            "artifact_id": request.artifact_id,
            "artifact_uri": request.artifact_uri,
            "parent_artifact_id": parent_artifact_id,
            "imported_from": request.imported_from,
            "imported_at": now,
            "stage_started_at": now,
            "stage_completed_at": now,
            "stale": False,
            "invalidation_reason": None,
            "updated_at": now,
        })

        await self._emit_event(
            OrchestrationEventType.artifact_imported,
            request.experiment_id,
            stage_job_id,
            request.pipeline_stage,
            payload={"artifact_id": request.artifact_id, "artifact_uri": request.artifact_uri},
        )

        logger.info(
            f"[IMPORT] stage={request.pipeline_stage} stage_job_id={stage_job_id} "
            f"artifact_id={request.artifact_id}"
        )

        return StageDispatchRequest(
            stage_job_id=stage_job_id,
            experiment_id=request.experiment_id,
            pipeline_stage=request.pipeline_stage,
            engine="imported",
            source=StageSource.imported,
        )

    # ─── Orchestration Status ─────────────────────────────────────────────────

    async def get_orchestration_status(
        self,
        experiment_id: str,
        stage_experiment_ids: List[str],
    ) -> ExperimentOrchestrationStatus:
        """
        Returns the full orchestration visibility payload for a root experiment.
        """
        stages: List[StageStatusItem] = []

        for exp_id in stage_experiment_ids:
            doc = await experiment_repository.get_experiment_by_id(exp_id)
            if doc:
                stages.append(StageStatusItem(
                    pipeline_stage=doc.get("type", "unknown"),
                    stage_job_id=doc.get("stage_job_id"),
                    status=StageStatus(doc.get("status", "queued")),
                    source=StageSource(doc.get("source", "live_compute")),
                    retry_count=doc.get("retry_count", 0),
                    partial_failure=doc.get("partial_failure", False),
                    dependency_failure=doc.get("dependency_failure", False),
                    stale=doc.get("stale", False),
                    invalidated_by_stage=doc.get("invalidated_by_stage"),
                    stage_started_at=doc.get("stage_started_at"),
                    stage_completed_at=doc.get("stage_completed_at"),
                    error=doc.get("error"),
                ))

        root_doc = await experiment_repository.get_experiment_by_id(experiment_id)
        overall_status = root_doc.get("status", "unknown") if root_doc else "unknown"

        return ExperimentOrchestrationStatus(
            experiment_id=experiment_id,
            overall_status=overall_status,
            stages=stages,
            events=[],
            updated_at=utc_now(),
        )

    # ─── Event Emitter ────────────────────────────────────────────────────────

    async def _emit_event(
        self,
        event_type: OrchestrationEventType,
        experiment_id: str,
        stage_job_id: str,
        pipeline_stage: str,
        payload: Optional[Dict[str, Any]] = None,
    ):
        """
        Emits a structured OrchestrationEvent.
        Phase D Hardening: event_id (UUID), event_sequence (monotonic per experiment),
        and correlation_id (= experiment_id) are now populated.
        Phase E will persist these to a durable store and stream via SSE/WebSocket.
        """
        # Increment per-experiment event sequence counter
        seq = _event_sequence_counters.get(experiment_id, 0) + 1
        _event_sequence_counters[experiment_id] = seq

        event = OrchestrationEvent(
            event_id=str(uuid.uuid4()),
            event_sequence=seq,
            correlation_id=experiment_id,
            event_type=event_type,
            experiment_id=experiment_id,
            stage_job_id=stage_job_id,
            pipeline_stage=pipeline_stage,
            timestamp=utc_now(),
            payload=payload or {},
        )
        logger.info(
            f"[ORCHESTRATION_EVENT] id={event.event_id} seq={event.event_sequence} "
            f"type={event.event_type.value} stage={pipeline_stage} "
            f"stage_job_id={stage_job_id} experiment_id={experiment_id}"
        )


stage_orchestrator_service = StageOrchestratorService()
