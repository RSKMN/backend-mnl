import logging
from typing import Dict, Any, List

logger = logging.getLogger("qudrugforge-pipeline-validation")

class PipelineValidationService:
    """
    Centralized service for evaluating the scientific readiness of a pipeline run 
    based on the available inputs for a project.
    """
    
    # Stages that inherently require a 3D protein structure to function properly
    STRUCTURAL_STAGES = {"docking", "gnina", "quantum", "simulation", "report"}
    
    def evaluate_readiness(self, inputs_doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates which pipeline stages are ready based on the provided inputs_doc.
        Returns a readiness matrix matching the requested frontend model.
        """
        has_fasta = bool(inputs_doc.get("protein_fasta_file_id"))
        has_pdb = bool(inputs_doc.get("protein_structure_file_id"))
        
        # Determine readiness flags
        generation_ready = has_fasta
        
        # Structural stages need BOTH FASTA (for generation) AND PDB (for docking/simulation)
        # Note: Depending on specific needs, if we resume from a prior run, we might already have SMILES.
        # But for a full pipeline validation perspective from inputs, we need both.
        structural_ready = has_fasta and has_pdb
        
        missing_inputs = []
        if not has_fasta:
            missing_inputs.append("protein_fasta_file_id")
        if not has_pdb:
            missing_inputs.append("protein_structure_file_id")
            
        full_pipeline_ready = generation_ready and structural_ready
        
        return {
            "generation_ready": generation_ready,
            "docking_ready": structural_ready,
            "gnina_ready": structural_ready,
            "quantum_ready": structural_ready,
            "simulation_ready": structural_ready,
            "report_ready": structural_ready,
            "full_pipeline_ready": full_pipeline_ready,
            "missing": missing_inputs
        }

    def validate_requested_stages(self, requested_stages: List[str], readiness: Dict[str, Any]):
        """
        Raises a DomainError if any requested stage is not ready according to the readiness matrix.
        """
        from app.core.exceptions import DomainError
        
        missing_for_request = set()
        
        for stage in requested_stages:
            if stage in ["target_ranking", "molecule_generation", "filtering", "admet"]:
                if not readiness.get("generation_ready"):
                    missing_for_request.add("protein_fasta_file_id")
            elif stage in self.STRUCTURAL_STAGES:
                if not readiness.get(f"{stage}_ready", False):
                    if not readiness.get("generation_ready"):
                        missing_for_request.add("protein_fasta_file_id")
                    if "protein_structure_file_id" in readiness.get("missing", []):
                        missing_for_request.add("protein_structure_file_id")

        if missing_for_request:
            missing_list = sorted(list(missing_for_request))
            missing_str = ", ".join(missing_list)
            raise DomainError(
                status_code=400,
                code="MISSING_SCIENTIFIC_INPUTS",
                message=f"Pipeline launch failed. Missing required scientific inputs for requested stages: {missing_str}"
            )

pipeline_validation_service = PipelineValidationService()
