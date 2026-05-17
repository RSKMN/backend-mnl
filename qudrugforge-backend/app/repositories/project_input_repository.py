import pymongo
from bson import ObjectId
from app.core.database import get_database
from typing import Optional
from app.utils.datetime import utc_now

class ProjectInputRepository:
    @property
    def collection(self):
        return get_database()["project_inputs"]

    async def ensure_indexes(self):
        await self.collection.create_index("project_id", unique=True)
        await self.collection.create_index("workspace_id")

    async def create_default_inputs(self, project_id: str, workspace_id: str, default_data: dict) -> dict:
        doc = {
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(workspace_id),
            **default_data
        }
        await self.collection.insert_one(doc)
        return await self.get_by_project_id(project_id)

    async def get_by_project_id(self, project_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(project_id):
            return None
        return await self.collection.find_one({"project_id": ObjectId(project_id)})

    async def get_or_create_default(self, project_id: str, workspace_id: str) -> dict:
        """
        Fetches the input configuration for the given project_id.
        If missing, initializes and saves a default configuration document.
        """
        inputs = await self.get_by_project_id(project_id)
        if inputs:
            return inputs
            
        now = utc_now()
        default_inputs = {
            "disease_type": None,
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
            "tumor_mutation_file_id": None,
            "rna_ihc_file_id": None,
            "organoid_response_file_id": None,
            "created_at": now,
            "updated_at": now
        }
        return await self.create_default_inputs(project_id, workspace_id, default_inputs)

    async def upsert_inputs(self, project_id: str, update_data: dict) -> Optional[dict]:
        if not ObjectId.is_valid(project_id):
            return None
            
        await self.collection.update_one(
            {"project_id": ObjectId(project_id)},
            {"$set": update_data},
            upsert=True
        )
        return await self.get_by_project_id(project_id)

    async def update_binding_site(self, project_id: str, binding_site_data: dict, updated_at: any) -> Optional[dict]:
        if not ObjectId.is_valid(project_id):
            return None
            
        await self.collection.update_one(
            {"project_id": ObjectId(project_id)},
            {"$set": {
                "binding_site": binding_site_data,
                "updated_at": updated_at
            }}
        )
        return await self.get_by_project_id(project_id)

    async def update_file_assignments(self, project_id: str, assignments: dict, updated_at: any) -> Optional[dict]:
        if not ObjectId.is_valid(project_id):
            return None
            
        update_doc = {**assignments, "updated_at": updated_at}
        await self.collection.update_one(
            {"project_id": ObjectId(project_id)},
            {"$set": update_doc}
        )
        return await self.get_by_project_id(project_id)

project_input_repository = ProjectInputRepository()
