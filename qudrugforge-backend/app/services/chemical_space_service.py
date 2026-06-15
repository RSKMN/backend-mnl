import logging
import hashlib
from typing import Optional, List, Dict, Any, Tuple
from bson import ObjectId
import json
import subprocess
import tempfile
import os
from pathlib import Path

from app.core.exceptions import AppException
from app.utils.datetime import utc_now

# Repositories
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.repositories.molecule_repository import molecule_repository

logger = logging.getLogger("qudrugforge-chemical-space-service")

def generate_deterministic_coords(identifier: str) -> Tuple[float, float, str]:
    """
    Generates stable, deterministic coordinates and cluster assignment from a string identifier.
    Guarantees coordinates are uniform and static for visual consistency.
    """
    h = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    
    # Extract segments as integers
    val_x = int(h[:8], 16)
    val_y = int(h[8:16], 16)
    val_cluster = int(h[16:24], 16)
    
    # Map val_x, val_y to range [-5.0, 5.0]
    x = round((val_x % 10000) / 1000.0 - 5.0, 3)
    y = round((val_y % 10000) / 1000.0 - 5.0, 3)
    
    # Map cluster
    clusters = ["A", "B", "C", "D"]
    cluster = clusters[val_cluster % len(clusters)]
    
    return x, y, cluster

class ChemicalSpaceService:
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

    async def get_chemical_space(
        self,
        project_id: str,
        user_id: str,
        limit: int = 500,
        status: Optional[str] = None,
        source: Optional[str] = None,
        recompute: bool = False
    ) -> dict:
        await self._get_project_and_workspace(project_id, user_id)

        # Build molecule query
        query = {"project_id": ObjectId(project_id)}
        if status:
            query["status"] = status
        if source:
            query["source"] = source

        total_count = await molecule_repository.collection.count_documents(query)
        cursor = molecule_repository.collection.find(query).limit(limit)
        molecules = await cursor.to_list(length=limit)

        points = []
        method_used = "stored"

        for mol in molecules:
            mol_id = str(mol["_id"])
            comp_id = mol.get("compound_id") or f"MOL-{mol_id[-6:]}"
            
            # Check if there is stored chemical_space in metadata
            meta = mol.get("metadata") or {}
            cs = meta.get("chemical_space")

            if cs and not recompute:
                x = cs.get("x")
                y = cs.get("y")
                cluster = cs.get("cluster") or "A"
                method_used = cs.get("method") or "stored"
            else:
                # Generate deterministic coordinates on the fly
                x, y, cluster = generate_deterministic_coords(mol_id)
                method_used = "deterministic_placeholder"

            points.append({
                "molecule_id": mol_id,
                "compound_id": comp_id,
                "x": x,
                "y": y,
                "cluster": cluster,
                "qed": mol.get("qed") or 0.0,
                "logp": mol.get("logp") or 0.0,
                "mw": mol.get("mw") or 0.0,
                "tpsa": mol.get("tpsa") or 0.0,
                "status": mol.get("status") or "uploaded"
            })

        # If some molecules have stored coords and others don't, set general method
        if recompute:
            method_used = "deterministic_placeholder"

        return {
            "project_id": project_id,
            "method": method_used,
            "points": points,
            "count": len(points)
        }

    async def recompute_chemical_space(
        self,
        project_id: str,
        user_id: str,
        method: str,
        limit: int = 1000,
        store: bool = True
    ) -> dict:
        await self._get_project_and_workspace(project_id, user_id)

        # Query all molecules up to limit
        query = {"project_id": ObjectId(project_id)}
        cursor = molecule_repository.collection.find(query).limit(limit)
        molecules = await cursor.to_list(length=limit)

        updated_count = 0
        points = []
        now = utc_now()

        resolved_method = "umap_rdkit_morgan"
        
        # Prepare input data for the subprocess
        input_data = []
        for mol in molecules:
            mol_id = str(mol["_id"])
            smiles = mol.get("smiles")
            if smiles:
                input_data.append({"molecule_id": mol_id, "smiles": smiles})
                
        # Run subprocess
        computed_coords = {}
        if input_data:
            with tempfile.TemporaryDirectory() as tmpdir:
                input_file = Path(tmpdir) / "input.json"
                output_file = Path(tmpdir) / "output.json"
                
                input_file.write_text(json.dumps(input_data), encoding="utf-8")
                
                q_ai_drug_dir = Path(__file__).parent.parent.parent.parent.parent / "q-ai-drug-new"
                if not q_ai_drug_dir.exists():
                    q_ai_drug_dir = Path("../../q-ai-drug-new").resolve()
                    
                script_path = q_ai_drug_dir / "scripts" / "compute_chemical_space.py"
                
                # Check for conda python path
                python_exe = os.environ.get("Q_AI_DRUG_PYTHON")
                if not python_exe:
                    conda_qadn_python = r"C:\Users\pc\anaconda3\envs\qadn\python.exe"
                    if os.path.exists(conda_qadn_python):
                        python_exe = conda_qadn_python
                    else:
                        python_exe = "python"
                
                cmd = [
                    python_exe, str(script_path),
                    "--input", str(input_file),
                    "--output", str(output_file),
                    "--clusters", "4"
                ]
                
                try:
                    logger.info(f"Running Chemical Space computation: {' '.join(cmd)}")
                    result = subprocess.run(
                        cmd,
                        cwd=str(q_ai_drug_dir),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False
                    )
                    
                    if result.returncode != 0:
                        logger.error(f"Chemical Space script failed: {result.stderr}")
                    elif output_file.exists():
                        computed_coords = json.loads(output_file.read_text(encoding="utf-8"))
                        logger.info(f"Loaded {len(computed_coords)} computed coordinates.")
                except Exception as e:
                    logger.error(f"Exception running Chemical Space script: {str(e)}")

        for mol in molecules:
            mol_id = str(mol["_id"])
            comp_id = mol.get("compound_id") or f"MOL-{mol_id[-6:]}"

            # Retrieve coords or fallback to deterministic
            mol_computed = computed_coords.get(mol_id)
            if mol_computed:
                x = mol_computed["x"]
                y = mol_computed["y"]
                cluster = mol_computed["cluster"]
                current_method = mol_computed["method"]
            else:
                x, y, cluster = generate_deterministic_coords(mol_id)
                current_method = "deterministic_placeholder"

            point = {
                "molecule_id": mol_id,
                "compound_id": comp_id,
                "x": x,
                "y": y,
                "cluster": cluster,
                "qed": mol.get("qed") or 0.0,
                "logp": mol.get("logp") or 0.0,
                "mw": mol.get("mw") or 0.0,
                "tpsa": mol.get("tpsa") or 0.0,
                "status": mol.get("status") or "uploaded"
            }
            points.append(point)

            if store:
                cs_meta = {
                    "x": x,
                    "y": y,
                    "cluster": cluster,
                    "method": current_method,
                    "computed_at": now
                }
                
                # Retrieve current metadata and update it safely
                meta = mol.get("metadata") or {}
                meta["chemical_space"] = cs_meta

                await molecule_repository.collection.update_one(
                    {"_id": mol["_id"]},
                    {"$set": {"metadata": meta, "updated_at": now}}
                )
                updated_count += 1

        return {
            "project_id": project_id,
            "method": resolved_method,
            "updated_count": updated_count,
            "points": points
        }

chemical_space_service = ChemicalSpaceService()
