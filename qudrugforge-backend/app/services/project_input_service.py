import logging
from bson import ObjectId
from typing import Optional, List, Dict, Any, Tuple
from app.repositories.project_repository import project_repository
from app.repositories.project_input_repository import project_input_repository
from app.repositories.file_metadata_repository import file_metadata_repository
from app.repositories.workspace_repository import workspace_repository
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-project-inputs-service")

class ProjectInputService:
    COMPATIBLE_TYPES = {
        "protein_fasta_file_id": ["protein_fasta"],
        "protein_structure_file_id": ["protein_structure"],
        "alphafold_structure_file_id": ["alphafold_structure", "protein_structure"],
        "reference_ligand_file_id": ["reference_ligand", "compound_library"],
        "compound_library_file_id": ["compound_library"],
        "assay_data_file_id": ["assay_data", "compound_library"],
        "admet_data_file_id": ["admet_data", "compound_library"],
        "tumor_mutation_file_id": ["tumor_mutation"],
        "rna_ihc_file_id": ["rna_ihc"],
        "organoid_response_file_id": ["organoid_response", "assay_data"]
    }

    async def check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace"
            )
        return membership

    async def get_project_inputs(self, project_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        return await project_input_repository.get_or_create_default(project_id, str(project["workspace_id"]))

    async def update_project_inputs(self, project_id: str, update_data: dict, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        
        if project.get("status") == "archived":
            raise AppException(
                status_code=400,
                code="PROJECT_ARCHIVED",
                message="Cannot update inputs of an archived project"
            )

        now = utc_now()
        
        clean_update = {
            "updated_at": now
        }
        
        fields = [
            "disease_type", "target_gene", "uniprot_id",
            "protein_fasta_file_id", "protein_structure_file_id", "alphafold_structure_file_id",
            "reference_ligand_file_id", "compound_library_file_id", "assay_data_file_id", "admet_data_file_id",
            "tumor_mutation_file_id", "rna_ihc_file_id", "organoid_response_file_id"
        ]
        
        for f in fields:
            if f in update_data:
                clean_update[f] = update_data[f]
                
        if "binding_site" in update_data and update_data["binding_site"] is not None:
            bs = update_data["binding_site"]
            bs_clean = {"mode": bs.get("mode", "box")}
            if bs_clean["mode"] == "box":
                if "box" in bs and bs["box"] is not None:
                    box = bs["box"]
                    if box.get("size_x", 0) <= 0 or box.get("size_y", 0) <= 0 or box.get("size_z", 0) <= 0:
                        raise AppException(
                            status_code=400,
                            code="INVALID_BINDING_SITE",
                            message="Box sizes must be positive numbers"
                        )
                    bs_clean["box"] = {
                        "center_x": box.get("center_x", 0.0),
                        "center_y": box.get("center_y", 0.0),
                        "center_z": box.get("center_z", 0.0),
                        "size_x": box.get("size_x", 20.0),
                        "size_y": box.get("size_y", 20.0),
                        "size_z": box.get("size_z", 20.0)
                    }
                    bs_clean["residues"] = []
            elif bs_clean["mode"] == "residues":
                bs_clean["residues"] = bs.get("residues") or []
                bs_clean["box"] = {
                    "center_x": 0.0, "center_y": 0.0, "center_z": 0.0,
                    "size_x": 20.0, "size_y": 20.0, "size_z": 20.0
                }
            clean_update["binding_site"] = bs_clean

        inputs = await project_input_repository.upsert_inputs(project_id, clean_update)
        
        if "disease_type" in clean_update and clean_update["disease_type"] is not None:
            await project_repository.update_project(project_id, {
                "disease_type": clean_update["disease_type"],
                "updated_at": now
            })
            
        return inputs

    async def assign_files(self, project_id: str, assignments: dict, user_id: str) -> dict:
        """
        Connects already uploaded scientific files to a project input configuration.
        """
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )

        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        if project.get("status") == "archived":
            raise AppException(
                status_code=400,
                code="PROJECT_ARCHIVED",
                message="Cannot update inputs of an archived project"
            )

        # Enforce project inputs document exists
        await project_input_repository.get_or_create_default(project_id, workspace_id)

        clean_assignments = {}

        for field, file_id in assignments.items():
            if field not in self.COMPATIBLE_TYPES:
                # Ignore fields that are not scientific file assignments
                continue

            if file_id is None:
                # Null means unassign
                clean_assignments[field] = None
                continue

            # Fetch file metadata
            file_meta = await file_metadata_repository.get_by_file_id(file_id)
            if not file_meta:
                raise AppException(
                    status_code=404,
                    code="FILE_NOT_FOUND",
                    message=f"File with ID '{file_id}' not found."
                )

            # Ensure file belongs to the same project
            if str(file_meta["project_id"]) != project_id:
                raise AppException(
                    status_code=403,
                    code="FILE_ACCESS_DENIED",
                    message="File does not belong to this project."
                )

            # Ensure file matches project workspace_id
            if str(file_meta["workspace_id"]) != workspace_id:
                raise AppException(
                    status_code=403,
                    code="FILE_ACCESS_DENIED",
                    message="Workspace mismatch on the assigned file."
                )

            # Validate compatible file_type
            file_type = file_meta.get("file_type")
            allowed_types = self.COMPATIBLE_TYPES[field]
            if file_type not in allowed_types:
                raise AppException(
                    status_code=400,
                    code="INVALID_INPUT_FILE_TYPE",
                    message=f"File type {file_type} cannot be assigned to {field}"
                )

            clean_assignments[field] = file_id

        # Update repository
        now = utc_now()
        updated = await project_input_repository.update_file_assignments(project_id, clean_assignments, now)
        if not updated:
            raise AppException(
                status_code=404,
                code="PROJECT_INPUT_NOT_FOUND",
                message="Project inputs not found"
            )
            
        return updated

    async def update_binding_site(self, project_id: str, binding_site_data: dict, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        
        if project.get("status") == "archived":
            raise AppException(
                status_code=400,
                code="PROJECT_ARCHIVED",
                message="Cannot update binding site of an archived project"
            )
            
        now = utc_now()
        
        mode = binding_site_data.get("mode")
        if mode not in ["box", "residues"]:
            raise AppException(
                status_code=400,
                code="INVALID_BINDING_SITE",
                message="Binding site mode must be 'box' or 'residues'"
            )

        bs_clean = {"mode": mode}
        if mode == "box":
            box = binding_site_data.get("box")
            if not box:
                raise AppException(
                    status_code=400,
                    code="INVALID_BINDING_SITE",
                    message="box configuration is required when mode is 'box'"
                )
            # Enforce positive sizes
            if box.get("size_x", 0) <= 0 or box.get("size_y", 0) <= 0 or box.get("size_z", 0) <= 0:
                raise AppException(
                    status_code=400,
                    code="INVALID_BINDING_SITE",
                    message="Box sizes must be positive numbers"
                )
            
            # Enforce center values are numbers
            for coord in ["center_x", "center_y", "center_z"]:
                if coord not in box or not isinstance(box[coord], (int, float)):
                    raise AppException(
                        status_code=400,
                        code="INVALID_BINDING_SITE",
                        message=f"{coord} must be a number"
                    )

            bs_clean["box"] = {
                "center_x": float(box.get("center_x", 0.0)),
                "center_y": float(box.get("center_y", 0.0)),
                "center_z": float(box.get("center_z", 0.0)),
                "size_x": float(box.get("size_x", 20.0)),
                "size_y": float(box.get("size_y", 20.0)),
                "size_z": float(box.get("size_z", 20.0))
            }
            bs_clean["residues"] = []
        elif mode == "residues":
            residues = binding_site_data.get("residues")
            if residues is None:
                raise AppException(
                    status_code=400,
                    code="INVALID_BINDING_SITE",
                    message="residues list is required when mode is 'residues'"
                )
            if not isinstance(residues, list) or len(residues) == 0:
                raise AppException(
                    status_code=400,
                    code="INVALID_BINDING_SITE",
                    message="residues list must be a non-empty list of non-empty strings"
                )
            for res in residues:
                if not res or not isinstance(res, str) or not res.strip():
                    raise AppException(
                        status_code=400,
                        code="INVALID_BINDING_SITE",
                        message="each residue must be a non-empty string"
                    )
            bs_clean["residues"] = residues
            bs_clean["box"] = {
                "center_x": 0.0, "center_y": 0.0, "center_z": 0.0,
                "size_x": 20.0, "size_y": 20.0, "size_z": 20.0
            }
            
        inputs = await project_input_repository.update_binding_site(project_id, bs_clean, now)
        return inputs

    async def check_completeness(self, project_id: str, user_id: str) -> dict:
        """
        Runs completeness heuristics on the assigned files and configurations.
        """
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )

        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        inputs = await project_input_repository.get_or_create_default(project_id, workspace_id)

        # Pre-calculate fields existence
        disease_type = inputs.get("disease_type") or project.get("disease_type")
        target_gene = inputs.get("target_gene")
        uniprot_id = inputs.get("uniprot_id")
        
        fasta_id = inputs.get("protein_fasta_file_id")
        struct_id = inputs.get("protein_structure_file_id")
        af_struct_id = inputs.get("alphafold_structure_file_id")
        ref_ligand_id = inputs.get("reference_ligand_file_id")
        lib_id = inputs.get("compound_library_file_id")
        admet_id = inputs.get("admet_data_file_id")

        binding_site = inputs.get("binding_site") or {}
        bs_mode = binding_site.get("mode", "box")
        
        bs_valid = False
        if bs_mode == "box":
            box = binding_site.get("box") or {}
            bs_valid = (
                box.get("size_x", 0) > 0 and 
                box.get("size_y", 0) > 0 and 
                box.get("size_z", 0) > 0
            )
        elif bs_mode == "residues":
            bs_valid = len(binding_site.get("residues") or []) > 0

        # Heuristics
        
        # 1. Target Setup
        ts_ready = bool(disease_type) and bool(
            target_gene or uniprot_id or struct_id or af_struct_id
        )
        ts_missing = []
        if not disease_type:
            ts_missing.append("Disease type configuration is missing.")
        if not (target_gene or uniprot_id or struct_id or af_struct_id):
            ts_missing.append("Target gene, UniProt ID, or structure file is required.")
        ts_warnings = []

        # 2. Docking
        docking_ready = bool(struct_id or af_struct_id) and bool(lib_id) and bs_valid
        docking_missing = []
        if not (struct_id or af_struct_id):
            docking_missing.append("Protein structure or AlphaFold file is missing.")
        if not lib_id:
            docking_missing.append("Compound library file is missing.")
        if not bs_valid:
            docking_missing.append("Binding site configuration is missing or invalid.")
        docking_warnings = []
        if bs_mode == "box" and bs_valid:
            docking_warnings.append("Binding box is user-defined and not literature-curated")

        # 3. GNINA
        gnina_ready = bool(struct_id or af_struct_id) and bool(lib_id) and bs_valid
        gnina_missing = []
        if not (struct_id or af_struct_id):
            gnina_missing.append("Protein structure or AlphaFold file is missing.")
        if not lib_id:
            gnina_missing.append("Compound library file is missing.")
        if not bs_valid:
            gnina_missing.append("Binding site configuration is missing or invalid.")
        gnina_warnings = []

        # 4. Quantum
        quantum_ready = bool(lib_id)
        quantum_missing = []
        if not lib_id:
            quantum_missing.append("Compound library file is missing.")
        quantum_warnings = [
            "Quantum reranking will be more meaningful after docking/GNINA results are available"
        ]

        # 5. ADMET
        admet_ready = bool(lib_id)
        admet_missing = []
        if not lib_id:
            admet_missing.append("Compound library file is missing.")
        admet_warnings = []
        if not admet_id:
            admet_warnings.append("ADMET prediction dataset is not assigned.")

        # 6. Simulations
        sim_ready = bool(struct_id or af_struct_id) and bool(ref_ligand_id or lib_id) and bs_valid
        sim_missing = []
        if not (struct_id or af_struct_id):
            sim_missing.append("Protein structure or AlphaFold file is missing.")
        if not (ref_ligand_id or lib_id):
            sim_missing.append("Reference ligand or compound library is required.")
        if not bs_valid:
            sim_missing.append("Binding site configuration is missing or invalid.")
        sim_warnings = []

        # 7. Reporting
        rep_ready = True
        rep_missing = []
        rep_warnings = []
        has_any_file = any([
            fasta_id, struct_id, af_struct_id, ref_ligand_id, lib_id, admet_id,
            inputs.get("tumor_mutation_file_id"), inputs.get("rna_ihc_file_id"), inputs.get("organoid_response_file_id")
        ])
        if not has_any_file and not target_gene:
            rep_warnings.append("No active file inputs or targets configured for report generations.")

        # Aggregate missing & warnings for root
        all_missing = list(set(
            ts_missing + docking_missing + gnina_missing + quantum_missing + admet_missing + sim_missing + rep_missing
        ))
        all_warnings = list(set(
            ts_warnings + docking_warnings + gnina_warnings + quantum_warnings + admet_warnings + sim_warnings + rep_warnings
        ))

        # Overall readiness
        overall_ready = ts_ready and docking_ready and gnina_ready and quantum_ready and admet_ready and sim_ready and rep_ready

        return {
            "overall_ready": overall_ready,
            "ready_for_docking": docking_ready,
            "ready_for_gnina": gnina_ready,
            "ready_for_quantum": quantum_ready,
            "ready_for_admet": admet_ready,
            "ready_for_simulations": sim_ready,
            "ready_for_reporting": rep_ready,
            "missing": all_missing,
            "warnings": all_warnings,
            "modules": {
                "target_setup": {
                    "ready": ts_ready,
                    "missing": ts_missing,
                    "warnings": ts_warnings
                },
                "docking": {
                    "ready": docking_ready,
                    "missing": docking_missing,
                    "warnings": docking_warnings
                },
                "gnina": {
                    "ready": gnina_ready,
                    "missing": gnina_missing,
                    "warnings": gnina_warnings
                },
                "quantum": {
                    "ready": quantum_ready,
                    "missing": quantum_missing,
                    "warnings": quantum_warnings
                },
                "admet": {
                    "ready": admet_ready,
                    "missing": admet_missing,
                    "warnings": admet_warnings
                },
                "simulations": {
                    "ready": sim_ready,
                    "missing": sim_missing,
                    "warnings": sim_warnings
                },
                "reporting": {
                    "ready": rep_ready,
                    "missing": rep_missing,
                    "warnings": rep_warnings
                }
            }
        }

project_input_service = ProjectInputService()
