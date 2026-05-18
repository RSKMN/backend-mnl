import logging
import hashlib
from typing import Optional, List, Dict, Any, Tuple
from bson import ObjectId

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

        # RDKit/UMAP is not yet connected/required for advanced Phase 15 computations
        # Keep deterministic_placeholder as primary or default fallback
        resolved_method = "deterministic_placeholder"
        if method in ("pca", "umap"):
            logger.info(f"Advanced UMAP/PCA chemical space computation requested but not enabled. Falling back to deterministic.")
            resolved_method = "deterministic_placeholder"

        for mol in molecules:
            mol_id = str(mol["_id"])
            comp_id = mol.get("compound_id") or f"MOL-{mol_id[-6:]}"

            # Generate deterministic coords
            x, y, cluster = generate_deterministic_coords(mol_id)

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
                    "method": resolved_method,
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
