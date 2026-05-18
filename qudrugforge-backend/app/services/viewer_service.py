import logging
from typing import Optional, List, Dict, Any, Tuple
from bson import ObjectId

from app.core.exceptions import AppException
from app.utils.datetime import utc_now

# Repositories
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.repositories.target_repository import target_repository
from app.repositories.molecule_repository import molecule_repository
from app.repositories.file_metadata_repository import file_metadata_repository
from app.repositories.docking_result_repository import docking_result_repository
from app.repositories.gnina_result_repository import gnina_result_repository
from app.repositories.project_input_repository import project_input_repository

logger = logging.getLogger("qudrugforge-viewer-service")

class ViewerService:
    async def _check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace",
            )
        return membership

    async def _get_project_and_workspace(self, project_id: str, user_id: str) -> Tuple[dict, str]:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found",
            )
        workspace_id = str(project["workspace_id"])
        await self._check_workspace_access(workspace_id, user_id)
        return project, workspace_id

    async def get_viewer_assets(self, project_id: str, user_id: str) -> dict:
        await self._get_project_and_workspace(project_id, user_id)

        # 1. Query files collection for the project
        cursor = file_metadata_repository.collection.find({"project_id": ObjectId(project_id)})
        files = await cursor.to_list(length=1000)

        assets = []
        seen_file_ids = set()

        for f in files:
            file_id = f.get("file_id")
            if not file_id:
                continue

            seen_file_ids.add(file_id)

            file_type = (f.get("file_type") or "").lower()
            source_module = (f.get("source_module") or "").lower()
            filename = (f.get("original_filename") or f.get("stored_filename") or "").lower()

            asset_type = "unknown"
            if file_type in ("protein_structure", "alphafold_structure") or "protein" in file_type or "alphafold" in file_type or any(ext in filename for ext in [".pdb", ".cif", ".mmcif"]):
                asset_type = "protein_structure"
            elif file_type in ("reference_ligand", "ligand") or any(ext in filename for ext in [".sdf", ".smi", ".smiles"]) or "ligand" in file_type:
                asset_type = "ligand"
            elif file_type == "docking_pose" or source_module == "docking" or "docking" in filename:
                asset_type = "docking_pose"
            elif file_type == "gnina_pose" or source_module == "gnina" or "gnina" in filename:
                asset_type = "gnina_pose"
            elif file_type == "simulation_trajectory" or source_module == "simulations" or "trajectory" in file_type or any(ext in filename for ext in [".dcd", ".xtc"]):
                asset_type = "trajectory"
            elif file_type == "interaction_fingerprint" or "fingerprint" in file_type:
                asset_type = "interaction_fingerprint"

            assets.append({
                "asset_id": file_id,
                "asset_type": asset_type,
                "file_id": file_id,
                "filename": f.get("original_filename") or f.get("stored_filename") or "unknown_file",
                "mime_type": f.get("mime_type") or "application/octet-stream",
                "source_module": f.get("source_module") or "unknown",
                "download_url": f"/api/v1/files/{file_id}/download",
                "preview_url": f"/api/v1/files/{file_id}/download",
                "linked_experiment_id": str(f.get("linked_experiment_id")) if f.get("linked_experiment_id") else None,
                "linked_result_id": None,
                "metadata": f.get("metadata") or {}
            })

        # 2. Query docking_results for pose files
        docking_cursor = docking_result_repository.collection.find({
            "project_id": ObjectId(project_id),
            "pose_file_id": {"$exists": True, "$ne": None}
        })
        docking_results = await docking_cursor.to_list(length=500)

        for result in docking_results:
            pose_file_id = result.get("pose_file_id")
            if not pose_file_id or pose_file_id in seen_file_ids:
                continue

            seen_file_ids.add(pose_file_id)

            filename = result.get("pose_filename") or f"pose_{result.get('compound_id') or 'docking'}.sdf"
            assets.append({
                "asset_id": pose_file_id,
                "asset_type": "docking_pose",
                "file_id": pose_file_id,
                "filename": filename,
                "mime_type": "chemical/x-mdl-sdfile",
                "source_module": "docking",
                "download_url": f"/api/v1/files/{pose_file_id}/download",
                "preview_url": f"/api/v1/files/{pose_file_id}/download",
                "linked_experiment_id": str(result.get("experiment_id")) if result.get("experiment_id") else None,
                "linked_result_id": str(result.get("_id")),
                "metadata": {
                    "compound_id": result.get("compound_id"),
                    "molecule_id": str(result.get("molecule_id")) if result.get("molecule_id") else None,
                    "target_id": str(result.get("target_id")) if result.get("target_id") else None,
                }
            })

        # 3. Query gnina_results for pose files
        gnina_cursor = gnina_result_repository.collection.find({
            "project_id": ObjectId(project_id),
            "pose_file_id": {"$exists": True, "$ne": None}
        })
        gnina_results = await gnina_cursor.to_list(length=500)

        for result in gnina_results:
            pose_file_id = result.get("pose_file_id")
            if not pose_file_id or pose_file_id in seen_file_ids:
                continue

            seen_file_ids.add(pose_file_id)

            filename = result.get("pose_filename") or f"pose_{result.get('compound_id') or 'gnina'}.sdf"
            assets.append({
                "asset_id": pose_file_id,
                "asset_type": "gnina_pose",
                "file_id": pose_file_id,
                "filename": filename,
                "mime_type": "chemical/x-mdl-sdfile",
                "source_module": "gnina",
                "download_url": f"/api/v1/files/{pose_file_id}/download",
                "preview_url": f"/api/v1/files/{pose_file_id}/download",
                "linked_experiment_id": str(result.get("experiment_id")) if result.get("experiment_id") else None,
                "linked_result_id": str(result.get("_id")),
                "metadata": {
                    "compound_id": result.get("compound_id"),
                    "molecule_id": str(result.get("molecule_id")) if result.get("molecule_id") else None,
                    "target_id": str(result.get("target_id")) if result.get("target_id") else None,
                }
            })

        return {
            "project_id": project_id,
            "assets": assets
        }

    async def get_protein_metadata(self, project_id: str, target_id: str, user_id: str) -> Optional[dict]:
        await self._get_project_and_workspace(project_id, user_id)

        target = await target_repository.get_target_by_id(target_id)
        if not target or str(target.get("project_id")) != project_id:
            raise AppException(
                status_code=404,
                code="TARGET_NOT_FOUND",
                message="Target not found in this project",
            )

        file_id = target.get("structure_file_id")
        if not file_id:
            # Fall back to project inputs
            proj_inputs = await project_input_repository.get_by_project_id(project_id)
            if proj_inputs:
                file_id = proj_inputs.get("protein_structure_file_id") or proj_inputs.get("alphafold_structure_file_id")

        if not file_id:
            return None

        file_meta = await file_metadata_repository.get_metadata_by_file_id(file_id)
        if not file_meta:
            # Safe default fallback structure
            return {
                "target_id": target_id,
                "file_id": file_id,
                "filename": "protein_structure.pdb",
                "download_url": f"/api/v1/files/{file_id}/download",
                "viewer_format": "pdb",
                "metadata": {}
            }

        filename = file_meta.get("original_filename") or file_meta.get("stored_filename") or ""
        ext = filename.split(".")[-1].lower() if "." in filename else "unknown"
        viewer_format = "unknown"
        if ext in ("pdb", "cif", "mmcif"):
            viewer_format = ext

        return {
            "target_id": target_id,
            "file_id": file_id,
            "filename": filename or f"target_{target_id}.pdb",
            "download_url": f"/api/v1/files/{file_id}/download",
            "viewer_format": viewer_format,
            "metadata": file_meta.get("metadata") or {}
        }

    async def get_ligand_metadata(self, project_id: str, molecule_id: str, user_id: str) -> dict:
        await self._get_project_and_workspace(project_id, user_id)

        molecule = await molecule_repository.get_molecule_by_id(molecule_id)
        if not molecule or str(molecule.get("project_id")) != project_id:
            raise AppException(
                status_code=404,
                code="MOLECULE_NOT_FOUND",
                message="Molecule not found in this project",
            )

        file_id = molecule.get("source_file_id")
        smiles = molecule.get("smiles")
        compound_id = molecule.get("compound_id")

        if not file_id:
            # Check if there is a ligand_asset link in metadata
            meta = molecule.get("metadata") or {}
            if "ligand_asset_file_id" in meta:
                file_id = meta["ligand_asset_file_id"]

        if file_id:
            file_meta = await file_metadata_repository.get_metadata_by_file_id(file_id)
            if file_meta:
                filename = file_meta.get("original_filename") or file_meta.get("stored_filename") or ""
                ext = filename.split(".")[-1].lower() if "." in filename else "unknown"
                viewer_format = "sdf" if ext == "sdf" else ("smiles" if ext in ("smi", "smiles") else "unknown")

                return {
                    "molecule_id": molecule_id,
                    "compound_id": compound_id,
                    "file_id": file_id,
                    "smiles": smiles,
                    "download_url": f"/api/v1/files/{file_id}/download",
                    "viewer_format": viewer_format,
                    "metadata": file_meta.get("metadata") or {}
                }

        # Virtual ligand fallback
        return {
            "molecule_id": molecule_id,
            "compound_id": compound_id,
            "file_id": None,
            "smiles": smiles,
            "download_url": None,
            "viewer_format": "smiles",
            "metadata": {}
        }

    async def get_pose_metadata(self, project_id: str, result_id: str, user_id: str) -> dict:
        await self._get_project_and_workspace(project_id, user_id)

        # Search docking
        result = await docking_result_repository.get_result_by_id(result_id)
        result_type = "docking"

        if not result:
            # Search gnina
            result = await gnina_result_repository.get_result_by_id(result_id)
            result_type = "gnina"

        if not result or str(result.get("project_id")) != project_id:
            raise AppException(
                status_code=404,
                code="RESULT_NOT_FOUND",
                message="Docking or GNINA result not found in this project",
            )

        pose_file_id = result.get("pose_file_id")
        if not pose_file_id:
            raise AppException(
                status_code=404,
                code="POSE_NOT_FOUND",
                message="No pose file is associated with this result",
            )

        molecule_id = str(result.get("molecule_id")) if result.get("molecule_id") else None
        target_id = str(result.get("target_id")) if result.get("target_id") else None

        # Build scores
        scores = {}
        if result_type == "docking":
            binding_energy = result.get("binding_energy") or result.get("score") or result.get("binding_affinity_kcal_mol")
            if binding_energy is not None:
                try:
                    scores["binding_affinity_kcal_mol"] = float(binding_energy)
                except ValueError:
                    pass
        else:  # gnina
            cnn_pose_score = result.get("cnn_pose_score")
            cnn_affinity = result.get("cnn_affinity")
            binding_energy = result.get("binding_energy") or result.get("score") or result.get("binding_affinity_kcal_mol")
            
            if binding_energy is not None:
                try:
                    scores["binding_affinity_kcal_mol"] = float(binding_energy)
                except ValueError:
                    pass
            if cnn_pose_score is not None:
                try:
                    scores["cnn_pose_score"] = float(cnn_pose_score)
                except ValueError:
                    pass
            if cnn_affinity is not None:
                try:
                    scores["cnn_affinity"] = float(cnn_affinity)
                except ValueError:
                    pass

        # Try to resolve format from files collection
        file_meta = await file_metadata_repository.get_metadata_by_file_id(pose_file_id)
        viewer_format = "sdf"  # Default
        metadata = {}
        if file_meta:
            filename = file_meta.get("original_filename") or file_meta.get("stored_filename") or ""
            ext = filename.split(".")[-1].lower() if "." in filename else "unknown"
            if ext in ("sdf", "pdbqt", "mol2"):
                viewer_format = ext
            metadata = file_meta.get("metadata") or {}

        return {
            "result_id": result_id,
            "result_type": result_type,
            "pose_file_id": pose_file_id,
            "download_url": f"/api/v1/files/{pose_file_id}/download",
            "viewer_format": viewer_format,
            "molecule_id": molecule_id,
            "target_id": target_id,
            "scores": scores,
            "metadata": metadata
        }

    async def get_interaction_fingerprint(self, project_id: str, result_id: str, user_id: str) -> dict:
        await self._get_project_and_workspace(project_id, user_id)

        # Search docking
        result = await docking_result_repository.get_result_by_id(result_id)
        result_type = "docking"

        if not result:
            # Search gnina
            result = await gnina_result_repository.get_result_by_id(result_id)
            result_type = "gnina"

        if not result or str(result.get("project_id")) != project_id:
            raise AppException(
                status_code=404,
                code="RESULT_NOT_FOUND",
                message="Result not found in this project",
            )

        if "interaction_fingerprint" in result and result["interaction_fingerprint"]:
            return {
                "result_id": result_id,
                "result_type": result_type,
                "interaction_fingerprint": result["interaction_fingerprint"],
                "available": True
            }

        # Safe empty default response
        return {
            "result_id": result_id,
            "result_type": result_type,
            "interaction_fingerprint": {
                "hydrogen_bonds": [],
                "hydrophobic_contacts": [],
                "pi_stacking": [],
                "salt_bridges": [],
                "metal_contacts": [],
                "raw": {}
            },
            "available": False
        }

viewer_service = ViewerService()
