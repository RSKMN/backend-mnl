"""
Phase D — Orchestration Schemas
Pydantic v2 schemas for stage-level orchestration, lineage, dependency tracking,
and real-time orchestration event metadata.

Principles:
- backend-mnl is the orchestration authority.
- Every stage execution is a distinct, versioned StageJob.
- Retries create new StageJobs linked via retry_parent_stage_id.
- Imported artifacts create StageJobs with source="imported".
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ─── Stage Status Enum ───────────────────────────────────────────────────────

class StageStatus(str, Enum):
    queued = "queued"
    waiting_for_dependency = "waiting_for_dependency"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    partial = "partial"
    retrying = "retrying"
    imported = "imported"


# ─── Stage Source Enum ───────────────────────────────────────────────────────

class StageSource(str, Enum):
    live_compute = "live_compute"
    imported = "imported"
    simulated = "simulated"


# ─── Orchestration Event Types ────────────────────────────────────────────────

class OrchestrationEventType(str, Enum):
    stage_started = "stage_started"
    stage_completed = "stage_completed"
    stage_failed = "stage_failed"
    stage_cancelled = "stage_cancelled"
    stage_retrying = "stage_retrying"
    dependency_resolved = "dependency_resolved"
    dependency_failed = "dependency_failed"
    downstream_invalidated = "downstream_invalidated"
    artifact_imported = "artifact_imported"
    retry_started = "retry_started"


# ─── Orchestration Event ──────────────────────────────────────────────────────

class OrchestrationEvent(BaseModel):
    """
    Real-time orchestration event emitted by backend-mnl when a stage
    transitions state. Used for frontend visibility and debug auditing.

    Phase D Hardening: event_id, event_sequence, correlation_id added
    to support future replay, ordering, and cross-stage tracing.
    """
    # ── Phase D Hardening: Event Identity ─────────────────────────────────────
    event_id: str = Field(default_factory=lambda: __import__('uuid').uuid4().__str__(),
                          description="Immutable UUID for this event. Never reused.")
    event_sequence: int = Field(default=0,
                                description="Monotonically increasing counter within experiment_id scope.")
    correlation_id: str = Field(default="",
                                description="Ties related events across stages. Typically equals experiment_id.")
    # ── Core Fields ───────────────────────────────────────────────────────────
    event_type: OrchestrationEventType
    experiment_id: str
    stage_job_id: str
    pipeline_stage: str
    timestamp: datetime
    payload: Dict[str, Any] = Field(default_factory=dict)


# ─── Downstream Invalidation Metadata ────────────────────────────────────────

class StaleMetadata(BaseModel):
    """
    Injected into a stage record when upstream changes invalidate this result.
    Phase D Hardening: added invalidation_reason for canonical auditability.
    """
    stale: bool = False
    invalidated_by_stage: Optional[str] = Field(
        default=None,
        description="stage_job_id of the upstream stage that caused invalidation"
    )
    invalidated_at: Optional[datetime] = None
    invalidation_reason: Optional[str] = Field(
        default=None,
        description="Canonical reason: upstream_recomputed | upstream_failed | artifact_replaced | parameter_changed | dependency_chain_stale"
    )


# ─── Operational Semantics (Phase E0 Prep) ───────────────────────────────────

class FailureType(str, Enum):
    execution_failure = "execution_failure"
    dependency_failure = "dependency_failure"
    timeout = "timeout"
    invalid_input = "invalid_input"
    missing_artifact = "missing_artifact"
    partial_validity = "partial_validity"
    unknown = "unknown"


class FailureClassification(BaseModel):
    failure_type: FailureType = FailureType.unknown
    failure_reason: Optional[str] = None
    recoverable: bool = False
    retry_recommended: bool = False


class CancellationSemantics(BaseModel):
    cancelled_by: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None


class ExecutionHeartbeat(BaseModel):
    last_heartbeat_at: Optional[datetime] = None
    heartbeat_timeout_seconds: Optional[int] = None
    stalled: bool = False


# ─── Stage Lineage ────────────────────────────────────────────────────────────

class StageLineage(BaseModel):
    """
    Mandatory lineage identifiers for every stage execution attempt.
    Forms the edges of the orchestration DAG.
    """
    experiment_id: str = Field(..., description="Root experiment UUID")
    stage_job_id: str = Field(..., description="UUID for this specific execution attempt")
    pipeline_stage: str = Field(..., description="Stage name (e.g., docking, gnina, admet)")
    parent_stage_job_id: Optional[str] = Field(
        default=None,
        description="Direct upstream dependency stage_job_id"
    )
    dependency_stage_ids: List[str] = Field(
        default_factory=list,
        description="All upstream stage_job_ids required for execution"
    )
    retry_parent_stage_id: Optional[str] = Field(
        default=None,
        description="stage_job_id of the previous failed attempt (if this is a retry)"
    )
    imported_from_stage_id: Optional[str] = Field(
        default=None,
        description="External artifact UUID if stage was fulfilled via manual import"
    )


# ─── Stage Job ────────────────────────────────────────────────────────────────

class StageJob(BaseModel):
    """
    A single, discrete stage execution unit tracked by backend-mnl.
    Replaces monolithic run_pipeline() assumptions.
    """
    # Identity
    stage_job_id: str = Field(..., description="Unique UUID for this execution attempt")
    experiment_id: str = Field(..., description="Root experiment UUID")
    pipeline_stage: str = Field(..., description="Stage name")

    # Orchestration State
    status: StageStatus = StageStatus.queued
    source: StageSource = StageSource.live_compute
    engine: str = Field(..., description="Execution engine (e.g. vina, gnina)")

    # Lineage
    lineage: StageLineage

    # Staleness
    stale_metadata: StaleMetadata = Field(default_factory=StaleMetadata)

    # Execution metadata
    retry_count: int = Field(default=0)
    stage_started_at: Optional[datetime] = None
    stage_completed_at: Optional[datetime] = None
    dependency_failure: bool = False
    partial_failure: bool = False
    error: Optional[str] = None
    
    # Phase E0 Minor Refinements
    failure_classification: Optional[FailureClassification] = None
    cancellation: Optional[CancellationSemantics] = None
    heartbeat: Optional[ExecutionHeartbeat] = None

    # Artifact linkage (Phase D Hardening: Immutability fields)
    output_artifact_ids: List[str] = Field(default_factory=list)
    artifact_id: Optional[str] = Field(default=None, description="UUID. Immutable once assigned.")
    artifact_uri: Optional[str] = Field(default=None, description="Storage URI. Frozen at creation.")
    artifact_version: Optional[str] = Field(default=None, description="Human-readable version within experiment.")
    artifact_hash: Optional[str] = Field(default=None, description="SHA-256. Set once, never mutated.")
    parent_artifact_id: Optional[str] = Field(default=None, description="artifact_id this supersedes.")
    imported_from: Optional[str] = None
    imported_at: Optional[datetime] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Stage Dispatch Request ───────────────────────────────────────────────────

class StageDispatchRequest(BaseModel):
    """
    Payload sent by backend-mnl to dispatch a stage to q-ai-drug-new
    (or any execution interface). Mandatory orchestration metadata envelope.
    """
    stage_job_id: str
    experiment_id: str
    pipeline_stage: str
    dependency_stage_ids: List[str] = Field(default_factory=list)
    retry_parent_stage_id: Optional[str] = None
    engine: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    source: StageSource = StageSource.live_compute

    # ── Phase D Hardening: Deterministic Execution Preparation ────────────────
    # Optional now — enforced in Phase E for stochastic stages.
    execution_seed: Optional[int] = Field(default=None, description="PRNG seed for stochastic stages.")
    parameter_hash: Optional[str] = Field(default=None, description="SHA-256 of serialized parameters.")
    config_snapshot_hash: Optional[str] = Field(default=None, description="SHA-256 of engine config snapshot.")
    execution_signature: Optional[str] = Field(default=None, description="Composite reproducibility fingerprint.")


# ─── Stage Dispatch Response ──────────────────────────────────────────────────

class StageDispatchResponse(BaseModel):
    """
    Response from an execution interface after accepting a stage dispatch.
    """
    stage_job_id: str
    status: StageStatus
    accepted: bool
    message: Optional[str] = None


# ─── Retry Request ────────────────────────────────────────────────────────────

class StageRetryRequest(BaseModel):
    """
    Issued by backend-mnl to retry a specific failed stage.
    """
    failed_stage_job_id: str = Field(..., description="The stage_job_id to retry")
    retry_downstream: bool = Field(
        default=False,
        description="If True, also reschedule all downstream stale stages"
    )


# ─── Import Stage Request ─────────────────────────────────────────────────────

class ImportStageArtifactRequest(BaseModel):
    """
    Used when a stage is satisfied by a manually uploaded artifact
    instead of live compute.
    """
    experiment_id: str
    pipeline_stage: str
    artifact_id: str
    artifact_uri: str
    imported_from: Optional[str] = None
    parent_stage_job_id: Optional[str] = None


# ─── Orchestration Status Response ────────────────────────────────────────────

class StageStatusItem(BaseModel):
    pipeline_stage: str
    stage_job_id: Optional[str] = None
    status: StageStatus
    source: StageSource = StageSource.live_compute
    retry_count: int = 0
    partial_failure: bool = False
    dependency_failure: bool = False
    stale: bool = False
    invalidated_by_stage: Optional[str] = None
    invalidated_at: Optional[datetime] = None
    invalidation_reason: Optional[str] = None
    stage_started_at: Optional[datetime] = None
    stage_completed_at: Optional[datetime] = None
    error: Optional[str] = None
    failure_classification: Optional[FailureClassification] = None
    cancellation: Optional[CancellationSemantics] = None


class ExperimentOrchestrationStatus(BaseModel):
    """
    Full orchestration visibility payload for a given experiment.
    Enables the frontend to accurately render stage-level progress.
    """
    experiment_id: str
    overall_status: str
    stages: List[StageStatusItem] = Field(default_factory=list)
    events: List[OrchestrationEvent] = Field(default_factory=list)
    updated_at: datetime
