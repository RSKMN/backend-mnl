import os
import re
import uuid
import shutil
import hashlib
import logging
from pathlib import Path
from bson import ObjectId
from typing import Optional, List, Dict, Any, Tuple

from app.core.config import settings
from app.core.exceptions import AppException
from app.utils.datetime import utc_now
from app.utils.safe_paths import resolve_and_validate_run_dir
from app.utils.csv_import import parse_csv_to_dicts, parse_numeric
from app.utils.admet_risk import classify_admet_result

# Repositories
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.repositories.file_metadata_repository import file_metadata_repository
from app.repositories.molecule_repository import molecule_repository
from app.repositories.docking_result_repository import docking_result_repository
from app.repositories.gnina_result_repository import gnina_result_repository
from app.repositories.quantum_result_repository import quantum_result_repository
from app.repositories.simulation_result_repository import simulation_result_repository
from app.repositories.admet_result_repository import admet_result_repository
from app.repositories.report_repository import report_repository
from app.repositories.experiment_repository import experiment_repository

logger = logging.getLogger("qudrugforge-artifact-import-service")

def copy_and_hash_file(src_path: Path, dest_path: Path) -> dict:
    """
    Copies a file to a new location, creating parent folders,
    and returns its size and SHA256 checksum.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    sha256 = hashlib.sha256()
    size_bytes = 0
    
    with open(src_path, "rb") as fsrc:
        with open(dest_path, "wb") as fdest:
            while chunk := fsrc.read(1024 * 64):
                size_bytes += len(chunk)
                fdest.write(chunk)
                sha256.update(chunk)
                
    return {
        "size_bytes": size_bytes,
        "checksum": sha256.hexdigest(),
    }

def get_flexible_value(row: dict, keys: list, default=None):
    """
    Looks up a key in a dictionary using a prioritized list of flexible column names.
    Supports exact and case-insensitive matching.
    """
    for k in keys:
        if k in row:
            return row[k]
    row_lower = {k.lower(): v for k, v in row.items()}
    for k in keys:
        if k.lower() in row_lower:
            return row_lower[k.lower()]
    return default


ADMET_ID_KEYS = ["molecule_id", "compound_id", "ligand_id", "smiles"]
ADMET_LIPINSKI_KEYS = ["lipinski_violations", "lipinski", "lipinski_pass"]
ADMET_TOXICITY_KEYS = [
    "ames_toxicity_risk",
    "ames_risk",
    "ames",
    "herg_risk",
    "hERG",
    "hepatotoxicity_risk",
    "hepatotoxicity",
    "tox21_risk",
    "tox21",
    "clintox_risk",
    "clintox",
]
ADMET_ADME_KEYS = [
    "solubility_score",
    "solubility",
    "permeability_score",
    "permeability",
    "cyp_inhibition_risk",
    "cyp",
    "clearance_risk",
    "clearance",
]
ADMET_OVERALL_KEYS = ["overall_risk", "recommendation", "admet_risk_score", "toxicity_risk"]
ADMET_MODEL_METRICS_HINTS = ["dataset", "endpoint", "roc_auc", "average_precision", "accuracy"]
ADMET_SIGNAL_KEYS = [
    *ADMET_LIPINSKI_KEYS,
    *ADMET_TOXICITY_KEYS,
    *ADMET_ADME_KEYS,
    *ADMET_OVERALL_KEYS,
]


def _row_has_admet_signal(row: dict) -> bool:
    keys = {str(key).lower() for key in row.keys()}
    for candidate in ADMET_SIGNAL_KEYS:
        if candidate.lower() in keys:
            return True
    return False


def _extract_admet_identity(row: dict) -> dict:
    molecule_id = get_flexible_value(row, ["molecule_id"])
    compound_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "name"])
    ligand_id = get_flexible_value(row, ["ligand_id"])
    smiles = get_flexible_value(row, ["smiles", "SMILES", "canonical_smiles"])
    return {
        "molecule_id": molecule_id,
        "compound_id": compound_id or ligand_id,
        "ligand_id": ligand_id,
        "smiles": smiles,
    }


def _normalize_admet_value(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"pass", "passed", "yes", "positive", "low", "safe"}:
        return "low"
    if lowered in {"fail", "failed", "no", "negative", "high", "unsafe"}:
        return "high"
    if lowered in {"medium", "moderate", "warning"}:
        return "medium"
    numeric = parse_numeric(value)
    return numeric if numeric is not None else value


def _extract_admet_row_payload(row: dict) -> tuple[dict, dict, bool]:
    identity = _extract_admet_identity(row)
    if not any(identity.values()):
        return {}, {}, False

    lipinski_violations = get_flexible_value(row, ["lipinski_violations"])
    if lipinski_violations is None:
        lipinski_value = get_flexible_value(row, ["lipinski", "lipinski_pass"])
        if lipinski_value is not None:
            text = str(lipinski_value).strip().lower()
            if isinstance(lipinski_value, bool):
                lipinski_violations = 0 if lipinski_value else 1
            elif text in {"pass", "passed", "true", "yes", "low", "ok"}:
                lipinski_violations = 0
            elif text in {"fail", "failed", "false", "no", "high"}:
                lipinski_violations = 1
            else:
                numeric = parse_numeric(lipinski_value)
                lipinski_violations = numeric if numeric is not None else None

    source_fields = {
        "lipinski_violations": lipinski_violations,
        "ames_toxicity_risk": get_flexible_value(row, ["ames_toxicity_risk", "ames_risk", "ames"]),
        "herg_risk": get_flexible_value(row, ["herg_risk", "hERG"]),
        "hepatotoxicity_risk": get_flexible_value(row, ["hepatotoxicity_risk", "hepatotoxicity"]),
        "tox21_risk": get_flexible_value(row, ["tox21_risk", "tox21"]),
        "clintox_risk": get_flexible_value(row, ["clintox_risk", "clintox"]),
        "solubility_score": get_flexible_value(row, ["solubility_score", "solubility"]),
        "permeability_score": get_flexible_value(row, ["permeability_score", "permeability"]),
        "cyp_inhibition_risk": get_flexible_value(row, ["cyp_inhibition_risk", "cyp"]),
        "clearance_risk": get_flexible_value(row, ["clearance_risk", "clearance"]),
        "overall_risk": get_flexible_value(row, ["overall_risk"]),
        "recommendation": get_flexible_value(row, ["recommendation"]),
        "admet_risk_score": get_flexible_value(row, ["admet_risk_score"]),
        "toxicity_risk": get_flexible_value(row, ["toxicity_risk", "toxicity", "risk"]),
    }

    row_has_signal = _row_has_admet_signal(row)
    if not row_has_signal:
        return {}, {}, False

    properties = {}
    mapped_keys = set(identity.keys()) | set(source_fields.keys()) | {
        "canonical_smiles",
        "lipinski",
        "lipinski_pass",
        "qed",
        "p_activity",
        "mw",
        "molecular_weight",
        "logp",
        "clogp",
        "status",
        "source",
    }
    for key, value in row.items():
        if key.lower() in {item.lower() for item in mapped_keys}:
            continue
        normalized = _normalize_admet_value(value)
        if normalized is not None:
            properties[key] = normalized

    doc = {
        **identity,
        "raw": dict(row),
        "properties": properties,
        "status": "imported",
        "metadata": {},
    }
    for key, value in source_fields.items():
        if value is not None:
            doc[key] = _normalize_admet_value(value)

    return doc, properties, True


def _admet_model_metrics_detected(rows: list[dict]) -> bool:
    if not rows:
        return False
    keys = {str(key).lower() for key in rows[0].keys()}
    return all(hint in keys for hint in ADMET_MODEL_METRICS_HINTS[:2]) or any(hint in keys for hint in ADMET_MODEL_METRICS_HINTS)

class ArtifactImportService:
    async def check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace"
            )
        return membership

    async def import_artifacts(
        self,
        project_id: str,
        user_id: str,
        run_name: Optional[str] = None,
        source_output_dir: Optional[str] = None,
        experiment_id: Optional[str] = None
    ) -> dict:
        # 1. Fetch and validate project
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )

        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        # Validate experiment_id if provided
        if experiment_id:
            experiment = await experiment_repository.get_experiment_by_id_and_project(experiment_id, project_id)
            if not experiment:
                raise AppException(
                    status_code=404,
                    code="EXPERIMENT_NOT_FOUND",
                    message="Experiment not found in this project"
                )
            if str(experiment["workspace_id"]) != workspace_id:
                raise AppException(
                    status_code=403,
                    code="WORKSPACE_ACCESS_DENIED",
                    message="Experiment workspace mismatch"
                )

        # 2. Safely resolve q-ai-drug run directory
        run_dir = resolve_and_validate_run_dir(run_name=run_name, source_output_dir=source_output_dir)
        actual_run_name = run_name or run_dir.name

        # Initialize session IDs
        import_id = str(uuid.uuid4())
        now = utc_now()
        new_exp_created = False

        # If experiment_id is not provided, create a new experiment automatically
        if not experiment_id:
            new_exp_doc = {
                "workspace_id": ObjectId(workspace_id),
                "project_id": ObjectId(project_id),
                "name": f"Q-AI-Drug Import ({actual_run_name})",
                "type": "q_ai_drug_import",
                "engine": "q_ai_drug",
                "status": "running",
                "progress": 10,
                "parameters": {
                    "run_name": actual_run_name,
                    "source_output_dir": source_output_dir
                },
                "input_file_ids": [],
                "output_file_ids": [],
                "logs": [
                    {
                        "timestamp": now,
                        "level": "info",
                        "message": "Experiment queued",
                        "stage": "queued",
                        "metadata": {}
                    },
                    {
                        "timestamp": now,
                        "level": "info",
                        "message": "Experiment status transitioned from queued to running",
                        "stage": "q_ai_drug_import",
                        "metadata": {}
                    }
                ],
                "q_ai_drug_job_id": None,
                "q_ai_drug_run_name": actual_run_name,
                "import_id": import_id,
                "error": None,
                "started_at": now,
                "completed_at": None,
                "created_by": ObjectId(user_id),
                "created_at": now,
                "updated_at": now
            }
            await experiment_repository.ensure_indexes()
            created_exp = await experiment_repository.create_experiment(new_exp_doc)
            experiment_id = str(created_exp["_id"])
            new_exp_created = True

        experiment_or_import_id = experiment_id

        # Log: q-ai-drug artifact import started
        await experiment_repository.append_log(experiment_or_import_id, {
            "timestamp": utc_now(),
            "level": "info",
            "message": "q-ai-drug artifact import started",
            "stage": "q_ai_drug_import",
            "metadata": {"run_name": actual_run_name, "import_id": import_id}
        })

        # Ensure database collections indexes are created
        await file_metadata_repository.ensure_indexes()
        await molecule_repository.ensure_indexes()
        await docking_result_repository.ensure_indexes()
        await gnina_result_repository.ensure_indexes()
        await quantum_result_repository.ensure_indexes()
        await simulation_result_repository.ensure_indexes()
        await admet_result_repository.ensure_indexes()
        await report_repository.ensure_indexes()

        # Tracks found, missing, and registered files
        found_files = []
        missing_files = []
        registered_file_records = []
        registered_file_ids = []
        warnings = []

        parsed_counts = {
            "molecules": 0,
            "docking_results": 0,
            "gnina_results": 0,
            "quantum_results": 0,
            "simulation_results": 0,
            "admet_results": 0,
            "reports": 0
        }

        # Define file mapping specs
        # structure: relative_path_in_run_dir -> (file_type, source_module, artifact_type, mime_type, optional_flag)
        file_specs = {
            "generated.csv": ("generated_candidates", "molecules", "csv", "text/csv", True),
            "filtered.csv": ("filtered_candidates", "molecules", "csv", "text/csv", True),
            "models/admet_model_metrics.csv": ("admet_model_metrics", "admet", "csv", "text/csv", True),
            "assets/ligand_asset_manifest.csv": ("q_ai_drug_artifact", "q_ai_drug", "csv", "text/csv", True),
            "docking/results.csv": ("docking_results", "docking", "csv", "text/csv", True),
            "gnina/results.csv": ("gnina_results", "gnina", "csv", "text/csv", True),
            "md/stability.csv": ("simulation_result", "simulations", "csv", "text/csv", True),
            "qm/qm_descriptors.csv": ("quantum_descriptor", "quantum", "csv", "text/csv", True),
            "qml/quantum_prefilter_scores.csv": ("quantum_score", "quantum", "csv", "text/csv", True),
            "qml/quantum_kernel_scores.csv": ("quantum_score", "quantum", "csv", "text/csv", True),
            "final_ranked_candidates.csv": ("q_ai_drug_artifact", "molecules", "csv", "text/csv", True),
            "top_candidates.csv": ("q_ai_drug_artifact", "molecules", "csv", "text/csv", True),
            "report.pdf": ("generated_report", "reports", "pdf", "application/pdf", True),
            "report.html": ("generated_report", "reports", "html", "text/html", True)
        }

        # Legacy ADMET search paths are still accepted if present.
        admet_paths = ["admet/results.csv", "admet/admet_results.csv"]
        admet_found_path = None
        for p in admet_paths:
            if (run_dir / p).exists():
                admet_found_path = p
                file_specs[p] = ("admet_data", "admet", "csv", "text/csv", True)
                break

        # Map of absolute source path -> registered file UUID string
        registered_file_map = {}

        # 3. Copy and Register Core Artifact Files
        for rel_path, spec in file_specs.items():
            src_file = run_dir / rel_path
            file_type, source_module, artifact_type, mime, is_optional = spec

            if not src_file.exists():
                if not is_optional:
                    raise AppException(
                        status_code=400,
                        code="ARTIFACT_FILE_COPY_FAILED",
                        message=f"Required file '{rel_path}' is missing from run directory."
                    )
                missing_files.append(rel_path)
                continue

            found_files.append(rel_path)

            # Generate target storage destination path
            storage_root = Path(settings.LOCAL_STORAGE_ROOT).resolve()
            
            # Treat reports differently as per prompt:
            # storage/reports/{workspace_id}/{project_id}/{report_id}/...
            if source_module == "reports":
                report_id = str(uuid.uuid4())
                local_rel_path = f"reports/{workspace_id}/{project_id}/{report_id}/{src_file.name}"
            else:
                local_rel_path = f"artifacts/{workspace_id}/{project_id}/{experiment_or_import_id}/{rel_path}"

            dest_file = storage_root / local_rel_path

            try:
                # Copy and compute hash
                file_info = copy_and_hash_file(src_file, dest_file)
            except Exception as e:
                logger.error(f"Copy failed for file '{src_file}' to '{dest_file}': {str(e)}")
                raise AppException(
                    status_code=500,
                    code="ARTIFACT_FILE_COPY_FAILED",
                    message=f"Failed to copy run artifact: {str(e)}"
                )

            # Register metadata in MongoDB
            file_uuid = str(uuid.uuid4())
            file_doc = {
                "file_id": file_uuid,
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "uploaded_by": ObjectId(user_id),
                "original_filename": src_file.name,
                "stored_filename": src_file.name,
                "file_type": file_type,
                "mime_type": mime,
                "local_path": local_rel_path,
                "size_bytes": file_info["size_bytes"],
                "checksum": file_info["checksum"],
                "source_module": source_module,
                "kind": "generated",
                "artifact_type": artifact_type,
                "linked_experiment_id": experiment_or_import_id,
                "storage_provider": "local",
                "metadata": {
                    "q_ai_drug_run_name": actual_run_name,
                    "relative_source_path": rel_path,
                    "import_id": import_id
                },
                "created_at": now,
                "updated_at": now
            }

            await file_metadata_repository.create_metadata(file_doc)
            registered_file_records.append(local_rel_path)
            registered_file_map[rel_path] = file_uuid
            registered_file_ids.append(file_uuid)

        # 4. Copy and Register GNINA Pose Files recursively
        pose_file_map = {}  # keyed by relative path, filename, stem, or candidate hint -> file_id

        def remember_pose_key(key: Optional[str], file_id: str) -> None:
            if not key:
                return
            key_str = str(key).replace("\\", "/").strip()
            if not key_str:
                return
            pose_file_map[key_str] = file_id
            pose_file_map[key_str.lower()] = file_id

        poses_dir = run_dir / "gnina" / "poses"
        if poses_dir.exists() and poses_dir.is_dir():
            for root, dirs, files in os.walk(poses_dir):
                for f in files:
                    src_pose = Path(root) / f
                    pose_rel = src_pose.relative_to(run_dir)
                    pose_rel_str = str(pose_rel).replace("\\", "/")

                    storage_root = Path(settings.LOCAL_STORAGE_ROOT).resolve()
                    local_rel_path = f"artifacts/{workspace_id}/{project_id}/{experiment_or_import_id}/{pose_rel_str}"
                    dest_pose = storage_root / local_rel_path

                    try:
                        file_info = copy_and_hash_file(src_pose, dest_pose)
                        
                        file_uuid = str(uuid.uuid4())
                        ext = src_pose.suffix.lstrip(".").lower()
                        mime = "chemical/x-mdl-sdfile" if ext == "sdf" else "application/octet-stream"

                        # Extract compound_id hints from relative pose directory or file name
                        parent_name = src_pose.parent.name
                        pose_stem = src_pose.stem
                        cand_id = parent_name if parent_name != "poses" else pose_stem

                        file_doc = {
                            "file_id": file_uuid,
                            "project_id": ObjectId(project_id),
                            "workspace_id": ObjectId(workspace_id),
                            "uploaded_by": ObjectId(user_id),
                            "original_filename": src_pose.name,
                            "stored_filename": src_pose.name,
                            "file_type": "gnina_pose",
                            "mime_type": mime,
                            "local_path": local_rel_path,
                            "size_bytes": file_info["size_bytes"],
                            "checksum": file_info["checksum"],
                            "source_module": "gnina",
                            "kind": "generated",
                            "artifact_type": ext,
                            "linked_experiment_id": experiment_or_import_id,
                            "storage_provider": "local",
                            "metadata": {
                                "q_ai_drug_run_name": actual_run_name,
                                "relative_source_path": pose_rel_str,
                                "import_id": import_id,
                                "candidate_id": cand_id
                            },
                            "created_at": now,
                            "updated_at": now
                        }

                        await file_metadata_repository.create_metadata(file_doc)
                        registered_file_records.append(local_rel_path)
                        remember_pose_key(cand_id, file_uuid)
                        remember_pose_key(parent_name, file_uuid)
                        remember_pose_key(pose_stem, file_uuid)
                        remember_pose_key(src_pose.name, file_uuid)
                        remember_pose_key(pose_rel_str, file_uuid)
                        remember_pose_key(str(Path("poses") / src_pose.name), file_uuid)
                        registered_file_ids.append(file_uuid)
                    except Exception as e:
                        logger.warning(f"Failed to copy and register individual pose file '{src_pose}': {str(e)}")
            found_files.append("gnina/poses/")
        else:
            missing_files.append("gnina/poses/")

        # Log: Registered X files
        await experiment_repository.append_log(experiment_or_import_id, {
            "timestamp": utc_now(),
            "level": "info",
            "message": f"Registered {len(registered_file_ids)} files",
            "stage": "q_ai_drug_import",
            "metadata": {"count": len(registered_file_ids)}
        })

        # 5. Populate and Cache Existing Molecules in Project to prevent duplicates
        existing_mols = await molecule_repository.collection.find({"project_id": ObjectId(project_id)}).to_list(length=None)
        existing_smiles = {m["smiles"] for m in existing_mols if "smiles" in m}
        existing_compound_ids = {m["compound_id"] for m in existing_mols if "compound_id" in m}
        compound_id_to_id = {m["compound_id"]: m["_id"] for m in existing_mols if "compound_id" in m}
        smiles_to_compound_id = {m["smiles"]: m["compound_id"] for m in existing_mols if "smiles" in m}

        max_suffix = await molecule_repository.get_max_compound_id_suffix(project_id)

        # 6. Parse and Import Candidates into Molecules Collection
        mol_sources = [
            ("generated.csv", "generated"),
            ("filtered.csv", "filtered"),
            ("final_ranked_candidates.csv", "selected"),
            ("top_candidates.csv", "selected")
        ]

        duplicate_skip_count = 0
        duplicate_update_count = 0

        admet_docs_by_key: dict[str, dict] = {}
        admet_sources_detected: list[str] = []

        def admet_record_key(identity: dict, row: dict) -> str:
            for field in ("molecule_id", "compound_id", "ligand_id", "smiles"):
                value = identity.get(field) or get_flexible_value(row, [field])
                if value not in (None, ""):
                    return f"{field}:{str(value).strip().lower()}"
            return f"row:{len(admet_docs_by_key)}"

        def merge_admet_record(row: dict, *, source_file_id: str, source_rel_path: str) -> bool:
            doc, properties, has_signal = _extract_admet_row_payload(row)
            if not has_signal:
                return False

            identity = {
                "molecule_id": doc.get("molecule_id"),
                "compound_id": doc.get("compound_id"),
                "ligand_id": doc.get("ligand_id"),
                "smiles": doc.get("smiles"),
            }
            key = admet_record_key(identity, row)
            existing_doc = admet_docs_by_key.get(key, {})

            merged_doc = {
                **existing_doc,
                **doc,
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "experiment_id": ObjectId(experiment_or_import_id),
                "import_id": import_id,
                "source": "q_ai_drug",
                "source_file_id": source_file_id,
                "properties": {
                    **existing_doc.get("properties", {}),
                    **properties,
                },
                "metadata": {
                    **existing_doc.get("metadata", {}),
                    "q_ai_drug_run_name": actual_run_name,
                    "relative_source_path": source_rel_path,
                    "import_id": import_id,
                },
                "raw": {
                    **existing_doc.get("raw", {}),
                    **dict(row),
                },
                "status": "imported",
                "created_at": existing_doc.get("created_at", now),
                "updated_at": now,
            }

            classified = classify_admet_result(merged_doc)
            merged_doc.update({
                "overall_risk": merged_doc.get("overall_risk") or classified["overall_risk"],
                "overall_risk_score": merged_doc.get("overall_risk_score") or classified["overall_risk_score"],
                "recommendation": merged_doc.get("recommendation") or classified["recommendation"],
                "risk_flags": classified["risk_flags"],
                "lipinski_violations": classified["lipinski_violations"],
                "critical_risks": classified["critical_risks"],
                "radar": classified["radar"],
                "badges": classified["badges"],
                "table_row": classified["table_row"],
                "ui": classified["ui"],
                "risk_level": merged_doc.get("overall_risk") or classified["overall_risk"],
                "risk_score": merged_doc.get("overall_risk_score") or classified["overall_risk_score"],
                "toxicity_risk": merged_doc.get("toxicity_risk") or classified["critical_risks"]["tox21_risk"]["level"],
            })

            admet_docs_by_key[key] = merged_doc
            if source_rel_path not in admet_sources_detected:
                admet_sources_detected.append(source_rel_path)
            return True

        for rel_path, status in mol_sources:
            if rel_path not in registered_file_map:
                continue

            file_uuid = registered_file_map[rel_path]
            rows = parse_csv_to_dicts(run_dir / rel_path)
            
            molecules_to_insert = []

            for row in rows:
                smiles = get_flexible_value(row, ["smiles", "canonical_smiles", "mol_smiles", "SMILES"])
                if not smiles:
                    continue

                comp_id = get_flexible_value(row, ["compound_id", "id", "molecule_id", "ligand_id", "name"])

                if smiles in existing_smiles:
                    existing_cid = smiles_to_compound_id[smiles]
                    existing_mid = compound_id_to_id.get(existing_cid)
                    
                    if existing_mid:
                        update_doc = {
                            "updated_at": now,
                            f"metadata.last_import_status_{status}": True,
                            f"metadata.import_session_{import_id}": True
                        }
                        if status == "selected" or (status == "filtered" and comp_id != "selected"):
                            update_doc["status"] = status

                        await molecule_repository.collection.update_one(
                            {"_id": existing_mid},
                            {"$set": update_doc}
                        )
                        duplicate_update_count += 1
                    else:
                        duplicate_skip_count += 1
                    continue

                if comp_id and comp_id in existing_compound_ids:
                    max_suffix += 1
                    comp_id = f"QDF-{max_suffix:06d}"

                if not comp_id:
                    max_suffix += 1
                    comp_id = f"QDF-{max_suffix:06d}"

                name = get_flexible_value(row, ["name", "compound_name", "molecule_name"])
                mw = parse_numeric(get_flexible_value(row, ["mw", "MW", "molecular_weight"]))
                logp = parse_numeric(get_flexible_value(row, ["logp", "LogP", "clogp"]))
                qed = parse_numeric(get_flexible_value(row, ["qed", "QED"]))
                tpsa = parse_numeric(get_flexible_value(row, ["tpsa", "TPSA"]))

                meta = {}
                mapped_keys = {"smiles", "canonical_smiles", "mol_smiles", "compound_id", "id", "molecule_id",
                               "ligand_id", "name", "compound_name", "molecule_name", "mw", "molecular_weight",
                               "logp", "clogp", "qed", "tpsa", "tpsa_max", "status", "source"}
                for k, v in row.items():
                    if k.lower() not in mapped_keys and k not in mapped_keys:
                        meta[k] = v

                meta["q_ai_drug_run_name"] = actual_run_name
                meta["import_id"] = import_id

                mol_doc = {
                    "project_id": ObjectId(project_id),
                    "workspace_id": ObjectId(workspace_id),
                    "source_file_id": file_uuid,
                    "compound_id": comp_id,
                    "smiles": smiles,
                    "name": name or comp_id,
                    "mw": mw,
                    "logp": logp,
                    "qed": qed,
                    "tpsa": tpsa,
                    "status": status,
                    "source": "q_ai_drug_import",
                    "metadata": meta,
                    "created_at": now,
                    "updated_at": now
                }

                molecules_to_insert.append(mol_doc)
                existing_smiles.add(smiles)
                existing_compound_ids.add(comp_id)
                smiles_to_compound_id[smiles] = comp_id

            if molecules_to_insert:
                inserted_count = await molecule_repository.create_many_molecules(molecules_to_insert)
                parsed_counts["molecules"] += inserted_count
                
                # Register the newly generated IDs in compound_id_to_id mapping
                for m in molecules_to_insert:
                    m_id = m.get("_id")
                    m_cid = m.get("compound_id")
                    if m_id and m_cid:
                        compound_id_to_id[m_cid] = m_id

            if rel_path in {"filtered.csv", "final_ranked_candidates.csv", "top_candidates.csv"}:
                if rel_path == "filtered.csv":
                    admet_source_id = registered_file_map[rel_path]
                    for row in rows:
                        merge_admet_record(row, source_file_id=admet_source_id, source_rel_path=rel_path)
                else:
                    # These files are scanned for ADMET-like columns and skipped cleanly when absent.
                    if any(_row_has_admet_signal(row) for row in rows):
                        admet_source_id = registered_file_map[rel_path]
                        for row in rows:
                            merge_admet_record(row, source_file_id=admet_source_id, source_rel_path=rel_path)

        if "models/admet_model_metrics.csv" in registered_file_map:
            metrics_rows = parse_csv_to_dicts(run_dir / "models/admet_model_metrics.csv")
            if _admet_model_metrics_detected(metrics_rows):
                warnings.append("Detected ADMET model metrics in models/admet_model_metrics.csv")

        # 7. Parse and Import Docking Results
        docking_csv = "docking/results.csv"
        if docking_csv in registered_file_map:
            file_uuid = registered_file_map[docking_csv]
            rows = parse_csv_to_dicts(run_dir / docking_csv)
            docking_docs = []

            for idx, row in enumerate(rows):
                comp_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "molecule_id", "name"])
                smiles = get_flexible_value(row, ["smiles", "SMILES", "canonical_smiles"])
                score = parse_numeric(get_flexible_value(row, ["score", "docking_score", "binding_energy", "affinity"]))
                rank = parse_numeric(get_flexible_value(row, ["rank"])) or (idx + 1)

                if not comp_id and not smiles:
                    continue

                pose_file_id = None
                pose_col = get_flexible_value(row, ["pose_file", "pose_path", "file"])
                pose_lookup_keys = [
                    pose_col,
                    str(pose_col).replace("\\", "/").lower() if pose_col else None,
                    Path(str(pose_col)).name if pose_col else None,
                    Path(str(pose_col)).stem if pose_col else None,
                    comp_id,
                    str(comp_id).lower() if comp_id else None,
                ]
                for key in pose_lookup_keys:
                    if key and key in pose_file_map:
                        pose_file_id = pose_file_map[key]
                        break

                meta = {}
                mapped_keys = {"compound_id", "id", "ligand_id", "molecule_id", "name", "smiles", "score", "docking_score",
                               "binding_energy", "affinity", "rank", "pose_file", "pose_path", "file"}
                for k, v in row.items():
                    if k.lower() not in mapped_keys and k not in mapped_keys:
                        meta[k] = v

                docking_doc = {
                    "project_id": ObjectId(project_id),
                    "workspace_id": ObjectId(workspace_id),
                    "experiment_id": ObjectId(experiment_or_import_id),
                    "import_id": import_id,
                    "molecule_id": None,
                    "compound_id": comp_id or f"CAND-{idx}",
                    "smiles": smiles or "",
                    "score": score,
                    "binding_energy": score,
                    "pose_file_id": pose_file_id,
                    "source_file_id": file_uuid,
                    "rank": int(rank),
                    "status": "imported",
                    "metadata": meta,
                    "created_at": now,
                    "updated_at": now
                }
                docking_docs.append(docking_doc)

            if docking_docs:
                inserted = await docking_result_repository.create_many(docking_docs)
                parsed_counts["docking_results"] += inserted

        # 8. Parse and Import GNINA Results
        gnina_csv = "gnina/results.csv"
        if gnina_csv in registered_file_map:
            file_uuid = registered_file_map[gnina_csv]
            rows = parse_csv_to_dicts(run_dir / gnina_csv)
            gnina_docs = []

            for idx, row in enumerate(rows):
                comp_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "molecule_id", "name"])
                smiles = get_flexible_value(row, ["smiles", "SMILES", "canonical_smiles"])
                cnn_score = parse_numeric(get_flexible_value(row, [
                    "cnn_score", "cnnscore", "cnn_pose_score", "gnina_cnn_score"
                ]))
                cnn_affinity = parse_numeric(get_flexible_value(row, [
                    "cnn_affinity", "cnnaffinity", "gnina_cnn_affinity"
                ]))
                binding_energy = parse_numeric(get_flexible_value(row, ["binding_energy", "affinity", "score"]))
                rank = parse_numeric(get_flexible_value(row, ["rank"])) or (idx + 1)

                if not comp_id and not smiles:
                    continue

                pose_file_id = None
                pose_col = get_flexible_value(row, ["pose_file", "pose_path", "file"])
                pose_lookup_keys = [
                    pose_col,
                    str(pose_col).replace("\\", "/").lower() if pose_col else None,
                    Path(str(pose_col)).name if pose_col else None,
                    Path(str(pose_col)).stem if pose_col else None,
                    comp_id,
                    str(comp_id).lower() if comp_id else None,
                ]
                for key in pose_lookup_keys:
                    if key and key in pose_file_map:
                        pose_file_id = pose_file_map[key]
                        break

                meta = {}
                mapped_keys = {"compound_id", "id", "ligand_id", "molecule_id", "name", "smiles", "cnn_score",
                               "cnnscore", "cnn_pose_score", "gnina_cnn_score", "cnn_affinity", "cnnaffinity",
                               "gnina_cnn_affinity", "binding_energy", "affinity", "score", "rank",
                               "pose_file", "pose_path", "file"}
                for k, v in row.items():
                    if k.lower() not in mapped_keys and k not in mapped_keys:
                        meta[k] = v

                gnina_doc = {
                    "project_id": ObjectId(project_id),
                    "workspace_id": ObjectId(workspace_id),
                    "experiment_id": ObjectId(experiment_or_import_id),
                    "import_id": import_id,
                    "compound_id": comp_id or f"CAND-{idx}",
                    "smiles": smiles or "",
                    "cnn_score": cnn_score,
                    "cnn_pose_score": cnn_score,
                    "cnn_affinity": cnn_affinity,
                    "binding_energy": binding_energy,
                    "pose_file_id": pose_file_id,
                    "source_file_id": file_uuid,
                    "rank": int(rank),
                    "status": "imported",
                    "source": "q_ai_drug",
                    "raw": dict(row),
                    "metadata": meta,
                    "created_at": now,
                    "updated_at": now
                }
                gnina_docs.append(gnina_doc)

            if gnina_docs:
                inserted = await gnina_result_repository.create_many(gnina_docs)
                parsed_counts["gnina_results"] += inserted

        # 9. Merge and Parse Quantum results
        qm_desc_csv = "qm/qm_descriptors.csv"
        q_pref_csv = "qml/quantum_prefilter_scores.csv"
        q_kern_csv = "qml/quantum_kernel_scores.csv"

        quantum_data_by_key = {}

        def quantum_key(kind: str, value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            value_str = str(value).strip()
            if not value_str:
                return None
            return f"{kind}:{value_str.lower()}"

        def extract_quantum_ids(row: dict) -> dict:
            molecule_id = get_flexible_value(row, ["molecule_id", "mol_id", "backend_molecule_id"])
            compound_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "candidate_id", "name"])
            ligand_id = get_flexible_value(row, ["ligand_id", "ligand", "candidate_id"])
            smiles = get_flexible_value(row, ["smiles", "SMILES", "canonical_smiles"])
            return {
                "molecule_id": molecule_id,
                "compound_id": compound_id or ligand_id,
                "ligand_id": ligand_id,
                "smiles": smiles,
            }

        def register_quantum_record_keys(rec: dict) -> None:
            for key in (
                quantum_key("molecule_id", rec.get("molecule_id")),
                quantum_key("compound_id", rec.get("compound_id")),
                quantum_key("ligand_id", rec.get("ligand_id")),
                quantum_key("smiles", rec.get("smiles")),
            ):
                if key:
                    quantum_data_by_key[key] = rec

        def get_quantum_record(ids: dict):
            for key in (
                quantum_key("molecule_id", ids.get("molecule_id")),
                quantum_key("compound_id", ids.get("compound_id")),
                quantum_key("ligand_id", ids.get("ligand_id")),
                quantum_key("smiles", ids.get("smiles")),
            ):
                if key and key in quantum_data_by_key:
                    rec = quantum_data_by_key[key]
                    if ids.get("molecule_id") and not rec.get("molecule_id"):
                        rec["molecule_id"] = ids["molecule_id"]
                    if ids.get("compound_id") and not rec.get("compound_id"):
                        rec["compound_id"] = ids["compound_id"]
                    if ids.get("ligand_id") and not rec.get("ligand_id"):
                        rec["ligand_id"] = ids["ligand_id"]
                    if ids.get("smiles") and not rec.get("smiles"):
                        rec["smiles"] = ids["smiles"]
                    register_quantum_record_keys(rec)
                    return rec

            rec = {
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "experiment_id": ObjectId(experiment_or_import_id),
                "import_id": import_id,
                "molecule_id": ids.get("molecule_id"),
                "compound_id": ids.get("compound_id"),
                "ligand_id": ids.get("ligand_id"),
                "smiles": ids.get("smiles"),
                "qm_descriptors": {},
                "quantum_prefilter_score": None,
                "quantum_kernel_score": None,
                "qml_score": None,
                "source_file_ids": [],
                "rank": None,
                "status": "imported",
                "source": "q_ai_drug",
                "raw": {
                    "qm_descriptors": [],
                    "quantum_prefilter": [],
                    "quantum_kernel": [],
                },
                "metadata": {},
                "created_at": now,
                "updated_at": now
            }
            register_quantum_record_keys(rec)
            return rec

        def append_quantum_source(rec: dict, file_uuid: str) -> None:
            if file_uuid not in rec["source_file_ids"]:
                rec["source_file_ids"].append(file_uuid)

        def set_descriptor_if_present(rec: dict, canonical_key: str, row: dict, keys: list) -> None:
            value = parse_numeric(get_flexible_value(row, keys))
            if value is not None:
                rec["qm_descriptors"][canonical_key] = value

        def add_raw_quantum_row(rec: dict, section: str, row: dict) -> None:
            rec.setdefault("raw", {}).setdefault(section, []).append(dict(row))

        if qm_desc_csv in registered_file_map:
            file_uuid = registered_file_map[qm_desc_csv]
            rows = parse_csv_to_dicts(run_dir / qm_desc_csv)
            for row in rows:
                ids = extract_quantum_ids(row)
                if not any(ids.values()):
                    continue

                rec = get_quantum_record(ids)
                append_quantum_source(rec, file_uuid)
                add_raw_quantum_row(rec, "qm_descriptors", row)

                set_descriptor_if_present(rec, "homo_ev", row, ["homo_ev", "homo", "HOMO"])
                set_descriptor_if_present(rec, "lumo_ev", row, ["lumo_ev", "lumo", "LUMO"])
                set_descriptor_if_present(rec, "gap_ev", row, ["gap_ev", "gap", "homo_lumo_gap", "orbital_gap"])
                set_descriptor_if_present(rec, "dipole_debye", row, ["dipole_debye", "dipole_moment_debye", "dipole"])

                mapped_keys = {
                    "compound_id", "id", "ligand_id", "candidate_id", "molecule_id", "mol_id",
                    "backend_molecule_id", "name", "smiles", "canonical_smiles",
                    "homo_ev", "homo", "HOMO", "lumo_ev", "lumo", "LUMO", "gap_ev", "gap",
                    "homo_lumo_gap", "orbital_gap", "dipole_debye", "dipole_moment_debye", "dipole"
                }
                mapped_lower = {k.lower() for k in mapped_keys}
                for k, v in row.items():
                    if k.lower() not in mapped_lower:
                        val = parse_numeric(v)
                        rec["qm_descriptors"][k] = val if val is not None else v

        if q_pref_csv in registered_file_map:
            file_uuid = registered_file_map[q_pref_csv]
            rows = parse_csv_to_dicts(run_dir / q_pref_csv)
            for idx, row in enumerate(rows):
                ids = extract_quantum_ids(row)
                score = parse_numeric(get_flexible_value(row, [
                    "quantum_prefilter_score", "prefilter_score", "score", "qml_score"
                ]))
                rank = parse_numeric(get_flexible_value(row, ["quantum_rank", "rank"]))
                if not any(ids.values()):
                    continue

                rec = get_quantum_record(ids)
                append_quantum_source(rec, file_uuid)
                add_raw_quantum_row(rec, "quantum_prefilter", row)

                rec["quantum_prefilter_score"] = score
                if rank is not None:
                    rec["rank"] = int(rank)
                    rec["quantum_rank"] = int(rank)
                
                mapped_keys = {
                    "compound_id", "id", "ligand_id", "candidate_id", "molecule_id", "mol_id",
                    "backend_molecule_id", "name", "smiles", "canonical_smiles",
                    "quantum_prefilter_score", "prefilter_score", "score", "qml_score",
                    "quantum_rank", "rank"
                }
                mapped_lower = {k.lower() for k in mapped_keys}
                for k, v in row.items():
                    if k.lower() not in mapped_lower:
                        rec["metadata"][f"prefilter_{k}"] = v

        if q_kern_csv in registered_file_map:
            file_uuid = registered_file_map[q_kern_csv]
            rows = parse_csv_to_dicts(run_dir / q_kern_csv)
            for idx, row in enumerate(rows):
                ids = extract_quantum_ids(row)
                kernel_score = parse_numeric(get_flexible_value(row, [
                    "quantum_kernel_score", "kernel_score", "qml_score", "score"
                ]))
                qml_score = parse_numeric(get_flexible_value(row, ["score", "qml_score"]))
                rank = parse_numeric(get_flexible_value(row, ["quantum_rank", "rank"])) or (idx + 1)

                if not any(ids.values()):
                    continue

                rec = get_quantum_record(ids)
                append_quantum_source(rec, file_uuid)
                add_raw_quantum_row(rec, "quantum_kernel", row)

                rec["quantum_kernel_score"] = kernel_score if kernel_score is not None else qml_score
                rec["qml_score"] = qml_score if qml_score is not None else kernel_score
                rec["rank"] = int(rank)
                rec["quantum_rank"] = int(rank)

                mapped_keys = {
                    "compound_id", "id", "ligand_id", "candidate_id", "molecule_id", "mol_id",
                    "backend_molecule_id", "name", "smiles", "canonical_smiles",
                    "quantum_kernel_score", "kernel_score", "qml_score", "score",
                    "quantum_rank", "rank"
                }
                mapped_lower = {k.lower() for k in mapped_keys}
                for k, v in row.items():
                    if k.lower() not in mapped_lower:
                        rec["metadata"][f"kernel_{k}"] = v

        all_unique_quantum_docs = []
        seen_ids = set()
        for doc in quantum_data_by_key.values():
            doc_id = id(doc)
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                
                if not doc["compound_id"]:
                    doc["compound_id"] = "CAND-QML"
                if not doc["smiles"]:
                    doc["smiles"] = ""
                if doc.get("molecule_id"):
                    try:
                        doc["molecule_id"] = ObjectId(doc["molecule_id"])
                    except Exception:
                        pass
                    
                all_unique_quantum_docs.append(doc)

        if all_unique_quantum_docs:
            inserted = await quantum_result_repository.create_many(all_unique_quantum_docs)
            parsed_counts["quantum_results"] += inserted

        # 10. Parse and Import Simulation MD Stability Results
        MD_RMSD_RMSF_KEYS = [
            "rmsd_avg", "avg_rmsd", "rmsd", "rmsd_max", "max_rmsd",
            "rmsf_avg", "avg_rmsf", "rmsf", "rmsf_max", "max_rmsf",
            "rmsd_average", "rmsd_fluctuation"
        ]
        MD_STABILITY_KEYS = [
            "stability_score", "stability", "md_stability_score", "stability_class", "pose_stable"
        ]
        MD_FILE_KEYS = [
            "trajectory_file", "trajectory_path", "structure_file", "structure_path"
        ]
        MD_ALL_SIGNAL_KEYS = MD_RMSD_RMSF_KEYS + MD_STABILITY_KEYS + MD_FILE_KEYS

        # First, locate all trajectory/structure files under md/ recursively
        md_file_map = {}  # keyed by relative path, filename, stem, or hint -> file_uuid

        md_dir = run_dir / "md"
        if md_dir.exists() and md_dir.is_dir():
            for root, dirs, files in os.walk(md_dir):
                for f in files:
                    src_file = Path(root) / f
                    md_rel = src_file.relative_to(run_dir)
                    md_rel_str = str(md_rel).replace("\\", "/")
                    
                    if md_rel_str in registered_file_map:
                        md_uuid = registered_file_map[md_rel_str]
                        md_file_map[md_rel_str] = md_uuid
                        md_file_map[src_file.name] = md_uuid
                        md_file_map[src_file.stem] = md_uuid
                        md_file_map[src_file.name.lower()] = md_uuid
                        md_file_map[src_file.stem.lower()] = md_uuid
                        continue
                    
                    ext = src_file.suffix.lower()
                    if ext not in {'.xtc', '.dcd', '.trr', '.nc', '.mdcrd', '.pdb', '.gro', '.csv', '.json'}:
                        continue
                    
                    storage_root = Path(settings.LOCAL_STORAGE_ROOT).resolve()
                    local_rel_path = f"artifacts/{workspace_id}/{project_id}/{experiment_or_import_id}/{md_rel_str}"
                    dest_file = storage_root / local_rel_path
                    
                    try:
                        file_info = copy_and_hash_file(src_file, dest_file)
                        file_uuid = str(uuid.uuid4())
                        
                        # Infer file_type and mime_type
                        if ext in ('.xtc', '.dcd', '.trr', '.nc', '.mdcrd'):
                            file_type = "simulation_trajectory"
                            mime = "application/octet-stream"
                        elif ext in ('.pdb', '.gro'):
                            file_type = "protein_structure"
                            mime = "chemical/x-pdb" if ext == ".pdb" else "application/octet-stream"
                        elif ext == ".csv":
                            file_type = "simulation_result"
                            mime = "text/csv"
                        elif ext == ".json":
                            file_type = "q_ai_drug_artifact"
                            mime = "application/json"
                        else:
                            file_type = "other"
                            mime = "application/octet-stream"
                            
                        file_doc = {
                            "file_id": file_uuid,
                            "project_id": ObjectId(project_id),
                            "workspace_id": ObjectId(workspace_id),
                            "uploaded_by": ObjectId(user_id),
                            "original_filename": src_file.name,
                            "stored_filename": src_file.name,
                            "file_type": file_type,
                            "mime_type": mime,
                            "local_path": local_rel_path,
                            "size_bytes": file_info["size_bytes"],
                            "checksum": file_info["checksum"],
                            "source_module": "simulations",
                            "kind": "generated",
                            "artifact_type": ext.lstrip("."),
                            "linked_experiment_id": experiment_or_import_id,
                            "storage_provider": "local",
                            "metadata": {
                                "q_ai_drug_run_name": actual_run_name,
                                "relative_source_path": md_rel_str,
                                "import_id": import_id,
                            },
                            "created_at": now,
                            "updated_at": now
                        }
                        await file_metadata_repository.create_metadata(file_doc)
                        registered_file_records.append(local_rel_path)
                        registered_file_map[md_rel_str] = file_uuid
                        registered_file_ids.append(file_uuid)
                        
                        md_file_map[md_rel_str] = file_uuid
                        md_file_map[src_file.name] = file_uuid
                        md_file_map[src_file.stem] = file_uuid
                        md_file_map[src_file.name.lower()] = file_uuid
                        md_file_map[src_file.stem.lower()] = file_uuid
                        
                    except Exception as e:
                        logger.warning(f"Failed to copy and register individual MD file '{src_file}': {str(e)}")

        # Next, search for stability.csv or other csv in md/ that has MD columns
        stability_csv_path = None
        stability_file_uuid = None
        
        if "md/stability.csv" in registered_file_map:
            stability_csv_path = run_dir / "md/stability.csv"
            stability_file_uuid = registered_file_map["md/stability.csv"]
        else:
            if md_dir.exists() and md_dir.is_dir():
                for root, dirs, files in os.walk(md_dir):
                    for f in files:
                        if f.endswith(".csv"):
                            candidate_path = Path(root) / f
                            try:
                                rows_tmp = parse_csv_to_dicts(candidate_path)
                                if rows_tmp:
                                    headers = {str(k).lower() for k in rows_tmp[0].keys()}
                                    if any(k.lower() in headers for k in MD_ALL_SIGNAL_KEYS):
                                        stability_csv_path = candidate_path
                                        rel_str = str(candidate_path.relative_to(run_dir)).replace("\\", "/")
                                        stability_file_uuid = md_file_map.get(rel_str) or md_file_map.get(f)
                                        break
                            except Exception:
                                pass
                    if stability_csv_path:
                        break

        if stability_csv_path:
            rows = parse_csv_to_dicts(stability_csv_path)
            if not rows:
                logger.warning(f"MD stability file {stability_csv_path} is empty, skipping simulation import.")
                warnings.append("MD stability file is empty; skipped simulation import.")
            else:
                headers = {str(k).lower() for k in rows[0].keys()}
                has_md_cols = any(k.lower() in headers for k in MD_ALL_SIGNAL_KEYS)
                if not has_md_cols:
                    logger.warning(f"No MD columns exist in stability file {stability_csv_path}, skipping simulation import.")
                    warnings.append("No MD/stability columns exist in stability file; skipped simulation import.")
                else:
                    from app.utils.simulation_stability import compute_stability_score, classify_stability
                    
                    sim_docs_to_insert = []
                    sim_docs_to_update = []
                    
                    for idx, row in enumerate(rows):
                        molecule_id = get_flexible_value(row, ["molecule_id"])
                        comp_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "molecule_id", "name"])
                        ligand_id = get_flexible_value(row, ["ligand_id"])
                        smiles = get_flexible_value(row, ["smiles", "SMILES", "canonical_smiles"])
                        target_id = get_flexible_value(row, ["target_id"])
                        target_gene = get_flexible_value(row, ["target_gene", "gene"])

                        # RMSD/RMSF
                        rmsd_avg = parse_numeric(get_flexible_value(row, ["rmsd_avg", "avg_rmsd", "rmsd", "rmsd_average"]))
                        rmsd_max = parse_numeric(get_flexible_value(row, ["rmsd_max", "max_rmsd"]))
                        rmsf_avg = parse_numeric(get_flexible_value(row, ["rmsf_avg", "avg_rmsf", "rmsf", "rmsf_average", "rmsd_fluctuation", "rmsd_fluc"]))
                        rmsf_max = parse_numeric(get_flexible_value(row, ["rmsf_max", "max_rmsf"]))

                        # Stability
                        stab_score = parse_numeric(get_flexible_value(row, ["stability_score", "stability", "md_stability_score"]))
                        stab_class = get_flexible_value(row, ["stability_class", "class", "status", "pose_stable"])

                        # Files
                        traj_file = get_flexible_value(row, ["trajectory_file", "trajectory_path"])
                        struct_file = get_flexible_value(row, ["structure_file", "structure_path"])

                        if not comp_id and not smiles:
                            continue

                        # Compute stability score and class if missing
                        if stab_score is None:
                            stab_score = compute_stability_score(
                                stability_score=None,
                                rmsd_avg=rmsd_avg,
                                rmsf_avg=rmsf_avg
                            )
                        
                        if stab_class is not None:
                            if isinstance(stab_class, bool):
                                stab_class = "stable" if stab_class else "unstable"
                            elif str(stab_class).strip().lower() in {"true", "stable", "1", "pass", "yes"}:
                                stab_class = "stable"
                            elif str(stab_class).strip().lower() in {"false", "unstable", "0", "fail", "no"}:
                                stab_class = "unstable"

                        if not stab_class:
                            stab_class = classify_stability(stab_score)

                        # Look up trajectory file and structure file in md_file_map
                        traj_file_id = None
                        if traj_file:
                            traj_lookup_keys = [
                                traj_file,
                                str(traj_file).replace("\\", "/").lower(),
                                Path(str(traj_file)).name,
                                Path(str(traj_file)).stem,
                                str(traj_file).lower(),
                                Path(str(traj_file)).name.lower(),
                                Path(str(traj_file)).stem.lower(),
                            ]
                            for key in traj_lookup_keys:
                                if key in md_file_map:
                                    traj_file_id = md_file_map[key]
                                    break
                            if not traj_file_id:
                                logger.warning(f"Optional trajectory file '{traj_file}' was not found/registered.")

                        struct_file_id = None
                        if struct_file:
                            struct_lookup_keys = [
                                struct_file,
                                str(struct_file).replace("\\", "/").lower(),
                                Path(str(struct_file)).name,
                                Path(str(struct_file)).stem,
                                str(struct_file).lower(),
                                Path(str(struct_file)).name.lower(),
                                Path(str(struct_file)).stem.lower(),
                            ]
                            for key in struct_lookup_keys:
                                if key in md_file_map:
                                    struct_file_id = md_file_map[key]
                                    break
                            if not struct_file_id:
                                logger.warning(f"Optional structure file '{struct_file}' was not found/registered.")

                        meta = {}
                        mapped_keys = {
                            "compound_id", "id", "ligand_id", "molecule_id", "name", "smiles", "canonical_smiles", "SMILES",
                            "target_id", "target_gene", "gene",
                            "rmsd_avg", "avg_rmsd", "rmsd", "rmsd_max", "max_rmsd",
                            "rmsf_avg", "avg_rmsf", "rmsf", "rmsf_max", "max_rmsf",
                            "stability_score", "stability", "md_stability_score", "stability_class", "class", "status",
                            "trajectory_file", "trajectory_path", "structure_file", "structure_path"
                        }
                        for k, v in row.items():
                            if k not in mapped_keys and k.lower() not in {item.lower() for item in mapped_keys}:
                                meta[k] = v

                        sim_doc = {
                            "project_id": ObjectId(project_id),
                            "workspace_id": ObjectId(workspace_id),
                            "experiment_id": ObjectId(experiment_or_import_id),
                            "import_id": import_id,
                            "molecule_id": ObjectId(molecule_id) if molecule_id else None,
                            "compound_id": comp_id or f"CAND-{idx}",
                            "ligand_id": ligand_id,
                            "smiles": smiles or "",
                            "target_id": target_id,
                            "target_gene": target_gene,
                            "md_stability_score": stab_score,
                            "stability_score": stab_score,
                            "rmsd": rmsd_avg,
                            "rmsd_avg": rmsd_avg,
                            "rmsd_max": rmsd_max,
                            "rmsf": rmsf_avg,
                            "rmsf_avg": rmsf_avg,
                            "rmsf_max": rmsf_max,
                            "stability_class": stab_class or "imported",
                            "source_file_id": stability_file_uuid,
                            "trajectory_file_id": traj_file_id,
                            "structure_file_id": struct_file_id,
                            "status": "imported",
                            "metadata": meta,
                            "raw": dict(row),
                            "updated_at": now
                        }

                        # Check if already exists in this experiment
                        existing_sim = None
                        if comp_id:
                            existing_sim = await simulation_result_repository.collection.find_one({
                                "project_id": ObjectId(project_id),
                                "experiment_id": ObjectId(experiment_or_import_id),
                                "compound_id": comp_id
                            })
                        
                        if existing_sim:
                            sim_doc["_id"] = existing_sim["_id"]
                            sim_docs_to_update.append(sim_doc)
                        else:
                            sim_doc["created_at"] = now
                            sim_docs_to_insert.append(sim_doc)

                    # Create or update records in MongoDB
                    if sim_docs_to_insert:
                        inserted = await simulation_result_repository.create_many(sim_docs_to_insert)
                        parsed_counts["simulation_results"] += inserted
                    for doc in sim_docs_to_update:
                        doc_id = doc.pop("_id")
                        await simulation_result_repository.collection.update_one(
                            {"_id": doc_id},
                            {"$set": doc}
                        )
                        parsed_counts["simulation_results"] += 1

        # 11. Finalize ADMET results from any molecule-level signals detected above.
        if admet_docs_by_key:
            admet_docs = list(admet_docs_by_key.values())
            inserted = await admet_result_repository.create_many(admet_docs)
            parsed_counts["admet_results"] += inserted
        elif any(path in registered_file_map for path in ("filtered.csv", "final_ranked_candidates.csv", "top_candidates.csv", "models/admet_model_metrics.csv", admet_found_path or "")):
            warnings.append("No molecule-level ADMET columns were found; skipped ADMET result import.")

        # 12. Register PDF & HTML Reports
        pdf_file_id = registered_file_map.get("report.pdf")
        html_file_id = registered_file_map.get("report.html")

        if pdf_file_id or html_file_id:
            report_doc = {
                "report_id": str(uuid.uuid4()),
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "experiment_id": ObjectId(experiment_or_import_id),
                "import_id": import_id,
                "title": f"Q-AI-Drug Discovery Run Report ({actual_run_name})",
                "report_type": "q_ai_drug",
                "pdf_file_id": pdf_file_id,
                "html_file_id": html_file_id,
                "status": "available",
                "metadata": {
                    "q_ai_drug_run_name": actual_run_name
                },
                "created_at": now,
                "updated_at": now
            }
            await report_repository.create_report(report_doc)
            parsed_counts["reports"] += 1

        # Duplicate logging/summary
        if duplicate_skip_count > 0:
            warnings.append(f"Skipped {duplicate_skip_count} redundant candidate SMILES already registered in project.")
        if duplicate_update_count > 0:
            warnings.append(f"Updated status/metadata for {duplicate_update_count} duplicate candidates.")

        # Log: Parsed results log
        parsed_msg = (
            f"Parsed molecules ({parsed_counts['molecules']}), "
            f"docking ({parsed_counts['docking_results']}), "
            f"GNINA ({parsed_counts['gnina_results']}), "
            f"quantum ({parsed_counts['quantum_results']}), "
            f"simulation ({parsed_counts['simulation_results']}), "
            f"ADMET ({parsed_counts['admet_results']}), "
            f"reports ({parsed_counts['reports']})"
        )
        await experiment_repository.append_log(experiment_or_import_id, {
            "timestamp": utc_now(),
            "level": "info",
            "message": parsed_msg,
            "stage": "q_ai_drug_import",
            "metadata": parsed_counts
        })

        # Log: q-ai-drug artifact import completed
        await experiment_repository.append_log(experiment_or_import_id, {
            "timestamp": utc_now(),
            "level": "info",
            "message": "q-ai-drug artifact import completed",
            "stage": "q_ai_drug_import",
            "metadata": {}
        })

        # Update experiment status, progress, and output_file_ids
        exp_status = "completed" if new_exp_created else "imported"
        await experiment_repository.update_experiment(experiment_or_import_id, {
            "status": exp_status,
            "progress": 100,
            "import_id": import_id,
            "output_file_ids": registered_file_ids,
            "completed_at": utc_now(),
            "updated_at": utc_now()
        })

        # Append status transition trace log to experiment
        await experiment_repository.append_log(experiment_or_import_id, {
            "timestamp": utc_now(),
            "level": "info",
            "message": f"Experiment status transitioned from running to {exp_status}",
            "stage": "q_ai_drug_import",
            "metadata": {}
        })

        return {
            "import_id": import_id,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "experiment_id": experiment_or_import_id,
            "run_name": actual_run_name,
            "source_dir": str(run_dir),
            "imported_files": found_files,
            "missing_files": missing_files,
            "parsed_collections": parsed_counts,
            "warnings": warnings
        }

artifact_import_service = ArtifactImportService()
