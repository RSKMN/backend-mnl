from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

class BindingSiteBox(BaseModel):
    center_x: float = 0.0
    center_y: float = 0.0
    center_z: float = 0.0
    size_x: float = 20.0
    size_y: float = 20.0
    size_z: float = 20.0

class BindingSite(BaseModel):
    mode: str = "box"
    residues: List[str] = Field(default_factory=list)
    box: BindingSiteBox = Field(default_factory=BindingSiteBox)

class BindingSiteUpdate(BaseModel):
    mode: str
    residues: Optional[List[str]] = None
    box: Optional[BindingSiteBox] = None

    @model_validator(mode="after")
    def validate_binding_site(self) -> 'BindingSiteUpdate':
        if self.mode not in ["box", "residues"]:
            raise ValueError("mode must be either 'box' or 'residues'")
            
        if self.mode == "box":
            if not self.box:
                raise ValueError("box configuration is required when mode is 'box'")
            if self.box.size_x <= 0 or self.box.size_y <= 0 or self.box.size_z <= 0:
                raise ValueError("Box sizes must be positive numbers")
        elif self.mode == "residues":
            if self.residues is None:
                raise ValueError("residues list is required when mode is 'residues'")
            if len(self.residues) == 0:
                raise ValueError("residues list cannot be empty")
            for res in self.residues:
                if not res or not res.strip():
                    raise ValueError("residue names cannot be empty or blank")
                    
        return self

class ProjectInputUpdate(BaseModel):
    disease_type: Optional[str] = None
    target_gene: Optional[str] = None
    uniprot_id: Optional[str] = None
    protein_fasta_file_id: Optional[str] = None
    protein_structure_file_id: Optional[str] = None
    alphafold_structure_file_id: Optional[str] = None
    reference_ligand_file_id: Optional[str] = None
    compound_library_file_id: Optional[str] = None
    assay_data_file_id: Optional[str] = None
    admet_data_file_id: Optional[str] = None
    tumor_mutation_file_id: Optional[str] = None
    rna_ihc_file_id: Optional[str] = None
    organoid_response_file_id: Optional[str] = None
    binding_site: Optional[BindingSiteUpdate] = None

class ProjectInputFileAssignment(BaseModel):
    protein_fasta_file_id: Optional[str] = None
    protein_structure_file_id: Optional[str] = None
    alphafold_structure_file_id: Optional[str] = None
    reference_ligand_file_id: Optional[str] = None
    compound_library_file_id: Optional[str] = None
    assay_data_file_id: Optional[str] = None
    admet_data_file_id: Optional[str] = None
    tumor_mutation_file_id: Optional[str] = None
    rna_ihc_file_id: Optional[str] = None
    organoid_response_file_id: Optional[str] = None

class ProjectInputResponse(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    disease_type: Optional[str] = None
    target_gene: Optional[str] = None
    uniprot_id: Optional[str] = None
    protein_fasta_file_id: Optional[str] = None
    protein_structure_file_id: Optional[str] = None
    alphafold_structure_file_id: Optional[str] = None
    binding_site: BindingSite
    reference_ligand_file_id: Optional[str] = None
    compound_library_file_id: Optional[str] = None
    assay_data_file_id: Optional[str] = None
    admet_data_file_id: Optional[str] = None
    tumor_mutation_file_id: Optional[str] = None
    rna_ihc_file_id: Optional[str] = None
    organoid_response_file_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mongo(cls, doc: dict):
        if not doc:
            return None
        return cls(
            id=str(doc["_id"]),
            project_id=str(doc["project_id"]),
            workspace_id=str(doc["workspace_id"]),
            disease_type=doc.get("disease_type"),
            target_gene=doc.get("target_gene"),
            uniprot_id=doc.get("uniprot_id"),
            protein_fasta_file_id=doc.get("protein_fasta_file_id"),
            protein_structure_file_id=doc.get("protein_structure_file_id"),
            alphafold_structure_file_id=doc.get("alphafold_structure_file_id"),
            binding_site=doc.get("binding_site", BindingSite().model_dump()),
            reference_ligand_file_id=doc.get("reference_ligand_file_id"),
            compound_library_file_id=doc.get("compound_library_file_id"),
            assay_data_file_id=doc.get("assay_data_file_id"),
            admet_data_file_id=doc.get("admet_data_file_id"),
            tumor_mutation_file_id=doc.get("tumor_mutation_file_id"),
            rna_ihc_file_id=doc.get("rna_ihc_file_id"),
            organoid_response_file_id=doc.get("organoid_response_file_id"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"]
        )

class InputCompletenessModuleStatus(BaseModel):
    ready: bool
    missing: List[str]
    warnings: List[str]

class InputCompletenessResponse(BaseModel):
    overall_ready: bool
    ready_for_docking: bool
    ready_for_gnina: bool
    ready_for_quantum: bool
    ready_for_admet: bool
    ready_for_simulations: bool
    ready_for_reporting: bool
    missing: List[str]
    warnings: List[str]
    modules: Dict[str, InputCompletenessModuleStatus]
