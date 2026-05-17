from bson import ObjectId
from typing import Optional, List, Dict, Any
from app.repositories.project_repository import project_repository
from app.repositories.project_input_repository import project_input_repository
from app.repositories.workspace_repository import workspace_repository
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

class ProjectService:
    async def check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace"
            )
        return membership

    async def create_project(self, workspace_id: str, name: str, description: Optional[str], disease_type: Optional[str], cancer_type: Optional[str], user_id: str) -> dict:
        await self.check_workspace_access(workspace_id, user_id)
        
        slug = await project_repository.generate_unique_slug(workspace_id, name)
        now = utc_now()
        
        project_doc = {
            "workspace_id": ObjectId(workspace_id),
            "name": name,
            "slug": slug,
            "description": description,
            "disease_type": disease_type,
            "cancer_type": cancer_type,
            "status": "draft",
            "created_by": ObjectId(user_id),
            "created_at": now,
            "updated_at": now
        }
        
        project = await project_repository.create_project(project_doc)
        
        # Create default project inputs
        default_inputs = {
            "disease_type": disease_type,
            "target_gene": None,
            "uniprot_id": None,
            "protein_fasta_file_id": None,
            "protein_structure_file_id": None,
            "alphafold_structure_file_id": None,
            "binding_site": {
                "mode": "box",
                "residues": [],
                "box": {
                    "center_x": 0.0,
                    "center_y": 0.0,
                    "center_z": 0.0,
                    "size_x": 20.0,
                    "size_y": 20.0,
                    "size_z": 20.0
                }
            },
            "reference_ligand_file_id": None,
            "compound_library_file_id": None,
            "assay_data_file_id": None,
            "admet_data_file_id": None,
            "created_at": now,
            "updated_at": now
        }
        
        await project_input_repository.create_default_inputs(str(project["_id"]), workspace_id, default_inputs)
        
        return project

    async def list_projects(self, workspace_id: str, status: Optional[str], search: Optional[str], skip: int, limit: int, user_id: str) -> tuple[List[dict], int]:
        await self.check_workspace_access(workspace_id, user_id)
        return await project_repository.list_projects(workspace_id, status, search, skip, limit)

    async def get_project(self, project_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
        
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        return project

    async def update_project(self, project_id: str, update_data: dict, user_id: str) -> dict:
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
                message="Cannot update an archived project"
            )
            
        # Allowed values for project status
        allowed_statuses = ["draft", "active", "paused", "completed", "archived"]
        
        clean_update = {}
        if "name" in update_data and update_data["name"] is not None:
            clean_update["name"] = update_data["name"]
            if update_data["name"] != project["name"]:
                clean_update["slug"] = await project_repository.generate_unique_slug(str(project["workspace_id"]), update_data["name"])
                
        if "description" in update_data:
            clean_update["description"] = update_data["description"]
            
        if "disease_type" in update_data:
            clean_update["disease_type"] = update_data["disease_type"]
            
        if "cancer_type" in update_data:
            clean_update["cancer_type"] = update_data["cancer_type"]
            
        if "status" in update_data and update_data["status"] is not None:
            status_val = update_data["status"]
            if status_val not in allowed_statuses:
                raise AppException(
                    status_code=400,
                    code="INVALID_PROJECT_STATUS",
                    message=f"Invalid project status. Allowed: {allowed_statuses}"
                )
            clean_update["status"] = status_val
            
        if clean_update:
            clean_update["updated_at"] = utc_now()
            project = await project_repository.update_project(project_id, clean_update)
            
        return project

    async def archive_project(self, project_id: str, user_id: str) -> bool:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        
        return await project_repository.archive_project(project_id, utc_now())

    async def get_project_overview(self, project_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        
        inputs = await project_input_repository.get_by_project_id(project_id)
        if not inputs:
            # Safely create default inputs
            now = utc_now()
            default_inputs = {
                "disease_type": project.get("disease_type"),
                "target_gene": None,
                "uniprot_id": None,
                "protein_fasta_file_id": None,
                "protein_structure_file_id": None,
                "alphafold_structure_file_id": None,
                "binding_site": {
                    "mode": "box",
                    "residues": [],
                    "box": {
                        "center_x": 0.0,
                        "center_y": 0.0,
                        "center_z": 0.0,
                        "size_x": 20.0,
                        "size_y": 20.0,
                        "size_z": 20.0
                    }
                },
                "reference_ligand_file_id": None,
                "compound_library_file_id": None,
                "assay_data_file_id": None,
                "admet_data_file_id": None,
                "created_at": now,
                "updated_at": now
            }
            inputs = await project_input_repository.create_default_inputs(project_id, str(project["workspace_id"]), default_inputs)

        # Check fields
        has_target_gene = bool(inputs.get("target_gene"))
        has_uniprot_id = bool(inputs.get("uniprot_id"))
        has_protein_structure = bool(inputs.get("protein_structure_file_id") or inputs.get("alphafold_structure_file_id") or inputs.get("protein_fasta_file_id"))
        has_compound_library = bool(inputs.get("compound_library_file_id"))
        
        binding_site = inputs.get("binding_site") or {}
        binding_site_configured = False
        mode = binding_site.get("mode", "box")
        if mode == "box":
            box = binding_site.get("box") or {}
            binding_site_configured = (
                box.get("size_x", 0) > 0 and 
                box.get("size_y", 0) > 0 and 
                box.get("size_z", 0) > 0 and 
                (box.get("center_x") != 0.0 or box.get("center_y") != 0.0 or box.get("center_z") != 0.0)
            )
        elif mode == "residues":
            binding_site_configured = len(binding_site.get("residues") or []) > 0
            
        next_steps = []
        if not has_target_gene:
            next_steps.append("Define target gene and UniProt ID.")
        if not has_protein_structure:
            next_steps.append("Upload protein structure or input UniProt ID/FASTA.")
        if not binding_site_configured:
            next_steps.append("Configure docking pocket / binding site parameters.")
        if not has_compound_library:
            next_steps.append("Select or upload compound library.")
        if not next_steps:
            if project.get("status") == "draft":
                next_steps.append("Activate the project to initiate Quantum AI discovery simulations.")
            else:
                next_steps.append("Docking and ADMET virtual screening pipelines are ready to execute.")

        return {
            "project": project,
            "input_summary": {
                "has_target_gene": has_target_gene,
                "has_uniprot_id": has_uniprot_id,
                "has_protein_structure": has_protein_structure,
                "has_compound_library": has_compound_library,
                "binding_site_configured": binding_site_configured
            },
            "counts": {
                "targets": 0,
                "molecules": 0,
                "experiments": 0,
                "reports": 0
            },
            "next_steps": next_steps
        }

    async def get_project_timeline(self, project_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        
        inputs = await project_input_repository.get_by_project_id(project_id)
        
        events = []
        
        # Project Created Event
        events.append({
            "type": "project_created",
            "title": "Project created",
            "timestamp": project["created_at"],
            "metadata": {
                "created_by": str(project["created_by"]),
                "name": project["name"]
            }
        })
        
        # Project Updated Event
        if project["updated_at"] > project["created_at"]:
            events.append({
                "type": "project_updated",
                "title": f"Project settings updated (status: {project.get('status')})",
                "timestamp": project["updated_at"],
                "metadata": {}
            })
            
        # Inputs Updated Event
        if inputs and inputs["updated_at"] > inputs["created_at"]:
            events.append({
                "type": "inputs_updated",
                "title": "Project inputs updated",
                "timestamp": inputs["updated_at"],
                "metadata": {
                    "target_gene": inputs.get("target_gene"),
                    "uniprot_id": inputs.get("uniprot_id")
                }
            })
            
        # Sort events by timestamp descending
        events.sort(key=lambda e: e["timestamp"], reverse=True)
        
        return {
            "items": events
        }

project_service = ProjectService()
