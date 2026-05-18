import logging
from typing import Optional, List, Dict, Any, Tuple
from bson import ObjectId

from app.core.exceptions import AppException
from app.utils.datetime import utc_now

# Repositories
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.repositories.molecule_repository import molecule_repository

logger = logging.getLogger("qudrugforge-similarity-service")

# Dynamic check for RDKit
try:
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from rdkit import DataStructs
    RDKIT_AVAILABLE = True
except ImportError:
    RDKIT_AVAILABLE = False

def get_ngrams(s: str, n: int = 3) -> set:
    if not s:
        return set()
    if len(s) <= n:
        return {s}
    return {s[i:i+n] for i in range(len(s) - n + 1)}

def compute_jaccard_similarity(s1: str, s2: str) -> float:
    """
    SMILES string character 3-gram Jaccard similarity fallback.
    Useful when RDKit is not installed in the current environment.
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    
    ngrams1 = get_ngrams(s1)
    ngrams2 = get_ngrams(s2)
    if not ngrams1 or not ngrams2:
        return 0.0
        
    union = len(ngrams1 | ngrams2)
    if union == 0:
        return 0.0
    return round(len(ngrams1 & ngrams2) / union, 4)

def compute_rdkit_similarity(s1: str, s2: str) -> float:
    """
    Morgan Fingerprint + Tanimoto similarity calculation.
    """
    if not RDKIT_AVAILABLE:
        return 0.0
    try:
        mol1 = Chem.MolFromSmiles(s1)
        mol2 = Chem.MolFromSmiles(s2)
        if not mol1 or not mol2:
            return 0.0
        fp1 = AllChem.GetMorganFingerprintAsBitVect(mol1, 2, nBits=2048)
        fp2 = AllChem.GetMorganFingerprintAsBitVect(mol2, 2, nBits=2048)
        return round(DataStructs.TanimotoSimilarity(fp1, fp2), 4)
    except Exception:
        return 0.0

def compute_similarity(s1: str, s2: str) -> Tuple[float, str]:
    if RDKIT_AVAILABLE:
        return compute_rdkit_similarity(s1, s2), "rdkit_tanimoto"
    else:
        return compute_jaccard_similarity(s1, s2), "smiles_jaccard_fallback"

class SimilarityService:
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

    async def search_similar_molecules(
        self,
        project_id: str,
        user_id: str,
        query_molecule_id: Optional[str] = None,
        query_smiles: Optional[str] = None,
        top_k: int = 20,
        min_similarity: float = 0.0,
        include_self: bool = False
    ) -> dict:
        await self._get_project_and_workspace(project_id, user_id)

        # 1. Resolve query SMILES
        resolved_smiles = query_smiles
        resolved_molecule_id = query_molecule_id

        if query_molecule_id:
            molecule = await molecule_repository.get_molecule_by_id(query_molecule_id)
            if not molecule or str(molecule.get("project_id")) != project_id:
                raise AppException(
                    status_code=404,
                    code="MOLECULE_NOT_FOUND",
                    message="Query molecule not found in this project",
                )
            resolved_smiles = molecule.get("smiles")
            
        if not resolved_smiles:
            raise AppException(
                status_code=400,
                code="VALIDATION_ERROR",
                message="Either query_molecule_id or query_smiles must be provided",
            )

        # 2. Get all molecules in the project
        cursor = molecule_repository.collection.find({"project_id": ObjectId(project_id)})
        all_molecules = await cursor.to_list(length=2000)

        # 3. Calculate similarities
        results = []
        method_used = "smiles_jaccard_fallback"

        for mol in all_molecules:
            mol_id = str(mol["_id"])
            if not include_self and resolved_molecule_id and mol_id == resolved_molecule_id:
                continue
            
            mol_smiles = mol.get("smiles")
            if not mol_smiles:
                continue

            similarity, method = compute_similarity(resolved_smiles, mol_smiles)
            method_used = method

            if similarity >= min_similarity:
                results.append({
                    "molecule_id": mol_id,
                    "compound_id": mol.get("compound_id") or f"MOL-{mol_id[-6:]}",
                    "smiles": mol_smiles,
                    "similarity": similarity,
                    "mw": mol.get("mw") or 0.0,
                    "logp": mol.get("logp") or 0.0,
                    "qed": mol.get("qed") or 0.0,
                    "status": mol.get("status") or "uploaded"
                })

        # Sort by similarity descending
        results.sort(key=lambda x: x["similarity"], reverse=True)
        top_results = results[:top_k]

        return {
            "project_id": project_id,
            "query": {
                "molecule_id": resolved_molecule_id,
                "smiles": resolved_smiles
            },
            "method": method_used,
            "results": top_results,
            "count": len(top_results)
        }

    async def get_similarity_matrix(
        self,
        project_id: str,
        user_id: str,
        limit: int = 50,
        molecule_ids: Optional[str] = None
    ) -> dict:
        await self._get_project_and_workspace(project_id, user_id)

        # Cap limit
        limit = min(max(limit, 1), 200)

        # 1. Fetch molecules
        query = {"project_id": ObjectId(project_id)}
        if molecule_ids:
            ids = [ObjectId(mid.strip()) for mid in molecule_ids.split(",") if ObjectId.is_valid(mid.strip())]
            if ids:
                query["_id"] = {"$in": ids}

        cursor = molecule_repository.collection.find(query).limit(limit)
        molecules = await cursor.to_list(length=limit)

        if not molecules:
            return {
                "project_id": project_id,
                "method": "rdkit_tanimoto" if RDKIT_AVAILABLE else "smiles_jaccard_fallback",
                "molecules": [],
                "matrix": []
            }

        # 2. Build pairwise similarity matrix
        matrix = []
        method_used = "smiles_jaccard_fallback"

        for i, mol_i in enumerate(molecules):
            row = []
            s_i = mol_i.get("smiles")
            for j, mol_j in enumerate(molecules):
                s_j = mol_j.get("smiles")
                if i == j:
                    sim = 1.0
                elif not s_i or not s_j:
                    sim = 0.0
                else:
                    sim, method = compute_similarity(s_i, s_j)
                    method_used = method
                row.append(sim)
            matrix.append(row)

        serialized_mols = [
            {
                "molecule_id": str(mol["_id"]),
                "compound_id": mol.get("compound_id") or f"MOL-{str(mol['_id'])[-6:]}"
            }
            for mol in molecules
        ]

        return {
            "project_id": project_id,
            "method": method_used,
            "molecules": serialized_mols,
            "matrix": matrix
        }

similarity_service = SimilarityService()
