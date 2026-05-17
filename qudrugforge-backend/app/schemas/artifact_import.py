from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict

class ArtifactImportRequest(BaseModel):
    run_name: Optional[str] = Field(default=None, description="The name of the q-ai-drug run directory, e.g., 'cancer_proof_v1'")
    source_output_dir: Optional[str] = Field(default=None, description="Direct relative or absolute path, e.g., 'outputs/cancer_proof_v1'")
    experiment_id: Optional[str] = Field(default=None, description="Optional experiment ID to link imported records to")

    @model_validator(mode="after")
    def validate_paths(self):
        if not self.run_name and not self.source_output_dir:
            raise ValueError("Either run_name or source_output_dir must be specified.")
        return self

class ImportSummaryResponse(BaseModel):
    import_id: str = Field(..., description="Unique generated UUID for this import session")
    project_id: str = Field(..., description="Linked project ID")
    workspace_id: str = Field(..., description="Linked workspace ID")
    experiment_id: Optional[str] = Field(default=None, description="Linked experiment ID if provided")
    run_name: str = Field(..., description="Name of the run that was imported")
    source_dir: str = Field(..., description="Absolute resolved source path of the import run")
    imported_files: List[str] = Field(default_factory=list, description="List of files that were successfully detected and registered")
    missing_files: List[str] = Field(default_factory=list, description="List of optional files that were missing")
    parsed_collections: Dict[str, int] = Field(default_factory=dict, description="Count of successfully parsed and stored records by category")
    warnings: List[str] = Field(default_factory=list, description="Any soft warnings or duplicate/skip notifications")
