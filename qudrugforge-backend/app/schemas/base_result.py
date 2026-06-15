from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from app.core.responses import ProvenanceMetadata

class BaseScientificResult(BaseModel):
    # Anchors (made optional to support mock test database objects and legacy entries)
    schema_version: Optional[str] = Field(default="1.0", description="Contract payload version")
    source: Optional[str] = Field(default=None, description="live_compute | imported | simulated")
    experiment_id: Optional[str] = Field(default=None, description="Orchestration lineage link")
    pipeline_stage: Optional[str] = Field(default=None, description="Exact pipeline step")
    engine: Optional[str] = Field(default=None, description="Exact algorithm (e.g. vina, gnina)")
    created_at: Optional[datetime] = Field(default=None, description="Immutable timestamp of generation")
    provenance: Optional[ProvenanceMetadata] = Field(default=None, description="Explicit execution history and boundary flags")

    # Uncertainty Normalization
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    uncertainty_score: Optional[float] = Field(default=None)
    applicability_domain: Optional[Dict[str, Any]] = Field(default=None)
    prediction_reliability: Optional[str] = Field(default=None)

    # ── Phase D Hardening: Artifact Immutability ──────────────────────────────
    # artifact_id is immutable once assigned. NEVER reused across retries.
    artifact_id: Optional[str] = Field(default=None, description="UUID assigned at artifact creation. Immutable.")
    artifact_uri: Optional[str] = Field(default=None, description="Storage URI. Frozen at creation.")
    # Versioning for human-readable lineage (e.g. '1', '2', '3')
    artifact_version: Optional[str] = Field(default=None, description="Semantic version within the experiment run.")
    # SHA-256 of artifact content — enables deduplication and reproducibility checks
    artifact_hash: Optional[str] = Field(default=None, description="SHA-256 content hash. Set once, never mutated.")
    # Points to the artifact this one supersedes in a retry/recompute chain
    parent_artifact_id: Optional[str] = Field(default=None, description="Prior artifact_id this result supersedes.")
    report_id: Optional[str] = Field(default=None)
    imported_from: Optional[str] = Field(default=None)

    # ── Phase D Hardening: Deterministic Execution Preparation ────────────────
    # Fields for reproducibility governance. Optional now; enforced in Phase E.
    execution_seed: Optional[int] = Field(default=None, description="PRNG seed for stochastic stages.")
    parameter_hash: Optional[str] = Field(default=None, description="SHA-256 of serialized run parameters.")
    config_snapshot_hash: Optional[str] = Field(default=None, description="SHA-256 of full engine config snapshot.")
    execution_signature: Optional[str] = Field(default=None, description="Composite fingerprint: parameter_hash + config_snapshot_hash + seed.")

    # Scientific Validity
    partial_result: Optional[bool] = Field(default=False)
    validation_status: Optional[str] = Field(
        default=None, 
        description="Phase E0 Prep: valid | malformed_artifact | partial_artifact | missing_artifact | corrupt_artifact"
    )

    # Aging / Staleness
    imported_at: Optional[datetime] = Field(default=None)
    artifact_age_days: Optional[int] = Field(default=None)
    stale: Optional[bool] = Field(default=False)
    invalidated_by_stage: Optional[str] = Field(default=None, description="stage_job_id that triggered staleness.")
    invalidated_at: Optional[datetime] = Field(default=None)
    invalidation_reason: Optional[str] = Field(default=None, description="Canonical reason: upstream_recomputed | upstream_failed | artifact_replaced | parameter_changed")

