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

        # ADMET search paths
        admet_paths = ["admet/results.csv", "admet/admet_results.csv"]
        admet_found_path = None
        for p in admet_paths:
            if (run_dir / p).exists():
                admet_found_path = p
                file_specs[p] = ("admet_data", "admet", "csv", "text/csv", True)
                break
        if not admet_found_path:
            missing_files.append("admet/results.csv")

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
        pose_file_map = {}  # keyed by compound_id -> file_id
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

                        # Extract compound_id from relative pose directory or file name
                        parent_name = src_pose.parent.name
                        cand_id = parent_name if "_" in parent_name else f.split(".")[0].split("_")[0]

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
                        pose_file_map[cand_id] = file_uuid
                        
                        # Store by filename as fallback
                        pose_file_map[src_pose.name] = file_uuid
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
                if pose_col and pose_col in pose_file_map:
                    pose_file_id = pose_file_map[pose_col]
                elif comp_id and comp_id in pose_file_map:
                    pose_file_id = pose_file_map[comp_id]

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
                cnn_score = parse_numeric(get_flexible_value(row, ["cnn_score", "cnnscore", "cnn_pose_score"]))
                cnn_affinity = parse_numeric(get_flexible_value(row, ["cnn_affinity", "cnnaffinity"]))
                binding_energy = parse_numeric(get_flexible_value(row, ["binding_energy", "affinity", "score"]))
                rank = parse_numeric(get_flexible_value(row, ["rank"])) or (idx + 1)

                if not comp_id and not smiles:
                    continue

                pose_file_id = None
                pose_col = get_flexible_value(row, ["pose_file", "pose_path", "file"])
                if pose_col and pose_col in pose_file_map:
                    pose_file_id = pose_file_map[pose_col]
                elif comp_id and comp_id in pose_file_map:
                    pose_file_id = pose_file_map[comp_id]

                meta = {}
                mapped_keys = {"compound_id", "id", "ligand_id", "molecule_id", "name", "smiles", "cnn_score",
                               "cnnscore", "cnn_pose_score", "cnn_affinity", "cnnaffinity", "binding_energy",
                               "affinity", "score", "rank", "pose_file", "pose_path", "file"}
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
                    "cnn_affinity": cnn_affinity,
                    "binding_energy": binding_energy,
                    "pose_file_id": pose_file_id,
                    "source_file_id": file_uuid,
                    "rank": int(rank),
                    "status": "imported",
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

        quantum_data_by_compound = {}
        quantum_data_by_smiles = {}

        def get_quantum_record(compound_id: str, smiles: str):
            if compound_id and compound_id in quantum_data_by_compound:
                return quantum_data_by_compound[compound_id]
            if smiles and smiles in quantum_data_by_smiles:
                return quantum_data_by_smiles[smiles]
            
            rec = {
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "experiment_id": ObjectId(experiment_or_import_id),
                "import_id": import_id,
                "compound_id": compound_id,
                "smiles": smiles,
                "qm_descriptors": {},
                "quantum_prefilter_score": None,
                "quantum_kernel_score": None,
                "qml_score": None,
                "source_file_ids": [],
                "rank": None,
                "status": "imported",
                "metadata": {},
                "created_at": now,
                "updated_at": now
            }
            if compound_id:
                quantum_data_by_compound[compound_id] = rec
            if smiles:
                quantum_data_by_smiles[smiles] = rec
            return rec

        if qm_desc_csv in registered_file_map:
            file_uuid = registered_file_map[qm_desc_csv]
            rows = parse_csv_to_dicts(run_dir / qm_desc_csv)
            for row in rows:
                comp_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "molecule_id", "name"])
                smiles = get_flexible_value(row, ["smiles", "SMILES"])
                if not comp_id and not smiles:
                    continue

                rec = get_quantum_record(comp_id, smiles)
                if file_uuid not in rec["source_file_ids"]:
                    rec["source_file_ids"].append(file_uuid)

                mapped_keys = {"compound_id", "id", "ligand_id", "molecule_id", "name", "smiles"}
                for k, v in row.items():
                    if k.lower() not in mapped_keys and k not in mapped_keys:
                        val = parse_numeric(v)
                        rec["qm_descriptors"][k] = val if val is not None else v

        if q_pref_csv in registered_file_map:
            file_uuid = registered_file_map[q_pref_csv]
            rows = parse_csv_to_dicts(run_dir / q_pref_csv)
            for row in rows:
                comp_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "molecule_id", "name"])
                smiles = get_flexible_value(row, ["smiles", "SMILES"])
                score = parse_numeric(get_flexible_value(row, ["quantum_prefilter_score", "prefilter_score", "score"]))
                if not comp_id and not smiles:
                    continue

                rec = get_quantum_record(comp_id, smiles)
                if file_uuid not in rec["source_file_ids"]:
                    rec["source_file_ids"].append(file_uuid)

                rec["quantum_prefilter_score"] = score
                
                mapped_keys = {"compound_id", "id", "ligand_id", "molecule_id", "name", "smiles",
                               "quantum_prefilter_score", "prefilter_score", "score"}
                for k, v in row.items():
                    if k.lower() not in mapped_keys and k not in mapped_keys:
                        rec["metadata"][f"prefilter_{k}"] = v

        if q_kern_csv in registered_file_map:
            file_uuid = registered_file_map[q_kern_csv]
            rows = parse_csv_to_dicts(run_dir / q_kern_csv)
            for idx, row in enumerate(rows):
                comp_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "molecule_id", "name"])
                smiles = get_flexible_value(row, ["smiles", "SMILES"])
                kernel_score = parse_numeric(get_flexible_value(row, ["quantum_kernel_score", "kernel_score", "qml_score"]))
                qml_score = parse_numeric(get_flexible_value(row, ["score", "qml_score"]))
                rank = parse_numeric(get_flexible_value(row, ["rank"])) or (idx + 1)

                if not comp_id and not smiles:
                    continue

                rec = get_quantum_record(comp_id, smiles)
                if file_uuid not in rec["source_file_ids"]:
                    rec["source_file_ids"].append(file_uuid)

                rec["quantum_kernel_score"] = kernel_score if kernel_score is not None else qml_score
                rec["qml_score"] = qml_score if qml_score is not None else kernel_score
                rec["rank"] = int(rank)

                mapped_keys = {"compound_id", "id", "ligand_id", "molecule_id", "name", "smiles",
                               "quantum_kernel_score", "kernel_score", "qml_score", "score", "rank"}
                for k, v in row.items():
                    if k.lower() not in mapped_keys and k not in mapped_keys:
                        rec["metadata"][f"kernel_{k}"] = v

        all_unique_quantum_docs = []
        seen_ids = set()
        for doc in list(quantum_data_by_compound.values()) + list(quantum_data_by_smiles.values()):
            doc_id = id(doc)
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                
                if not doc["compound_id"]:
                    doc["compound_id"] = "CAND-QML"
                if not doc["smiles"]:
                    doc["smiles"] = ""
                    
                all_unique_quantum_docs.append(doc)

        if all_unique_quantum_docs:
            inserted = await quantum_result_repository.create_many(all_unique_quantum_docs)
            parsed_counts["quantum_results"] += inserted

        # 10. Parse and Import Simulation MD Stability Results
        sim_csv = "md/stability.csv"
        if sim_csv in registered_file_map:
            file_uuid = registered_file_map[sim_csv]
            rows = parse_csv_to_dicts(run_dir / sim_csv)
            sim_docs = []

            for idx, row in enumerate(rows):
                comp_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "molecule_id", "name"])
                smiles = get_flexible_value(row, ["smiles", "SMILES", "canonical_smiles"])
                score = parse_numeric(get_flexible_value(row, ["md_stability_score", "stability_score", "score"]))
                rmsd = parse_numeric(get_flexible_value(row, ["rmsd", "RMSD"]))
                rmsf = parse_numeric(get_flexible_value(row, ["rmsf", "RMSF"]))
                stab_class = get_flexible_value(row, ["stability_class", "class", "status"])

                if not comp_id and not smiles:
                    continue

                meta = {}
                mapped_keys = {"compound_id", "id", "ligand_id", "molecule_id", "name", "smiles",
                               "md_stability_score", "stability_score", "score", "rmsd", "RMSD", "rmsf", "RMSF",
                               "stability_class", "class", "status"}
                for k, v in row.items():
                    if k.lower() not in mapped_keys and k not in mapped_keys:
                        meta[k] = v

                sim_doc = {
                    "project_id": ObjectId(project_id),
                    "workspace_id": ObjectId(workspace_id),
                    "experiment_id": ObjectId(experiment_or_import_id),
                    "import_id": import_id,
                    "compound_id": comp_id or f"CAND-{idx}",
                    "smiles": smiles or "",
                    "md_stability_score": score,
                    "rmsd": rmsd,
                    "rmsf": rmsf,
                    "stability_class": stab_class or "imported",
                    "source_file_id": file_uuid,
                    "status": "imported",
                    "metadata": meta,
                    "created_at": now,
                    "updated_at": now
                }
                sim_docs.append(sim_doc)

            if sim_docs:
                inserted = await simulation_result_repository.create_many(sim_docs)
                parsed_counts["simulation_results"] += inserted

        # 11. Parse and Import ADMET Results (Optional)
        if admet_found_path and admet_found_path in registered_file_map:
            file_uuid = registered_file_map[admet_found_path]
            rows = parse_csv_to_dicts(run_dir / admet_found_path)
            admet_docs = []

            for idx, row in enumerate(rows):
                comp_id = get_flexible_value(row, ["compound_id", "id", "ligand_id", "molecule_id", "name"])
                smiles = get_flexible_value(row, ["smiles", "SMILES"])
                tox_risk = get_flexible_value(row, ["toxicity_risk", "toxicity", "risk"])

                if not comp_id and not smiles:
                    continue

                props = {}
                mapped_keys = {"compound_id", "id", "ligand_id", "molecule_id", "name", "smiles",
                               "toxicity_risk", "toxicity", "risk"}
                for k, v in row.items():
                    if k.lower() not in mapped_keys and k not in mapped_keys:
                        val = parse_numeric(v)
                        props[k] = val if val is not None else v

                admet_doc = {
                    "project_id": ObjectId(project_id),
                    "workspace_id": ObjectId(workspace_id),
                    "experiment_id": ObjectId(experiment_or_import_id),
                    "import_id": import_id,
                    "compound_id": comp_id or f"CAND-{idx}",
                    "smiles": smiles or "",
                    "properties": props,
                    "toxicity_risk": tox_risk,
                    "status": "imported",
                    "source_file_id": file_uuid,
                    "metadata": {
                        "q_ai_drug_run_name": actual_run_name
                    },
                    "created_at": now,
                    "updated_at": now
                }
                admet_docs.append(admet_doc)

            if admet_docs:
                inserted = await admet_result_repository.create_many(admet_docs)
                parsed_counts["admet_results"] += inserted

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
