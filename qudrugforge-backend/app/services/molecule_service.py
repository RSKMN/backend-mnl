import csv
import os
import logging
from bson import ObjectId
from typing import Optional, List, Tuple, Set
from app.repositories.project_repository import project_repository
from app.repositories.molecule_repository import molecule_repository
from app.repositories.file_metadata_repository import file_metadata_repository
from app.repositories.workspace_repository import workspace_repository
from app.storage.service import storage_service
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-molecule-service")

class MoleculeService:
    async def check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace"
            )
        return membership

    async def list_molecules(
        self,
        project_id: str,
        status: Optional[str],
        search: Optional[str],
        source_file_id: Optional[str],
        skip: int,
        limit: int,
        user_id: str
    ) -> Tuple[List[dict], int]:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        return await molecule_repository.list_molecules(project_id, status, search, source_file_id, skip, limit)

    async def get_molecule(self, project_id: str, molecule_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        
        molecule = await molecule_repository.get_molecule_by_id(molecule_id)
        if not molecule or str(molecule["project_id"]) != project_id:
            raise AppException(
                status_code=404,
                code="MOLECULE_NOT_FOUND",
                message="Molecule not found"
            )
            
        return molecule

    async def filter_molecules(self, project_id: str, criteria: dict, user_id: str) -> List[dict]:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        await self.check_workspace_access(str(project["workspace_id"]), user_id)
        
        now = utc_now()
        mark_filtered = criteria.get("mark_filtered", False)
        
        return await molecule_repository.filter_molecules(project_id, criteria, mark_filtered, now)

    async def import_molecules(self, project_id: str, request_data: dict, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )
            
        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)
        
        source_file_id = request_data.get("source_file_id")
        if not source_file_id:
            raise AppException(
                status_code=400,
                code="VALIDATION_ERROR",
                message="source_file_id is required."
            )
            
        # Get file metadata
        file_meta = await file_metadata_repository.get_by_file_id(source_file_id)
        if not file_meta:
            raise AppException(
                status_code=404,
                code="FILE_NOT_FOUND",
                message="File metadata not found"
            )
            
        if str(file_meta["project_id"]) != project_id:
            raise AppException(
                status_code=403,
                code="FILE_ACCESS_DENIED",
                message="File does not belong to this project."
            )
            
        if str(file_meta["workspace_id"]) != workspace_id:
            raise AppException(
                status_code=403,
                code="FILE_ACCESS_DENIED",
                message="Workspace mismatch on file."
            )
            
        # Validate type & extension
        allowed_types = ["compound_library", "assay_data"]
        if file_meta.get("file_type") not in allowed_types:
            raise AppException(
                status_code=400,
                code="INVALID_IMPORT_FILE",
                message=f"File must be compound_library or assay_data type. Got: {file_meta.get('file_type')}"
            )
            
        filename = file_meta.get("original_filename", "").lower()
        _, ext = os.path.splitext(filename)
        
        if ext == ".sdf":
            raise AppException(
                status_code=400,
                code="SDF_NOT_SUPPORTED_YET",
                message="SDF structure files are not supported for import in Phase 6."
            )
            
        allowed_extensions = [".csv", ".tsv", ".smi", ".txt"]
        if ext not in allowed_extensions:
            raise AppException(
                status_code=400,
                code="INVALID_IMPORT_FILE",
                message=f"Unsupported file extension. Allowed: {allowed_extensions}"
            )
            
        # Open physical file
        provider = storage_service.get_provider()
        if not await provider.exists(file_meta["local_path"]):
            raise AppException(
                status_code=404,
                code="FILE_MISSING_ON_STORAGE",
                message="The assigned scientific file is missing from local disk storage."
            )
            
        resolved_path = await provider.get_file_path(file_meta["local_path"])
        
        # Determine delimiter
        delimiter = ","
        if ext == ".tsv":
            delimiter = "\t"
        elif ext in [".smi", ".txt"]:
            delimiter = " "
            
        # Sniff delimiter & header from first line
        try:
            with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline()
                if not first_line.strip():
                    raise AppException(
                        status_code=400,
                        code="INVALID_IMPORT_FILE",
                        message="Import file is empty."
                    )
                if ext in [".smi", ".txt"]:
                    if "\t" in first_line:
                        delimiter = "\t"
                    elif "," in first_line:
                        delimiter = ","
                    elif " " in first_line:
                        delimiter = " "
        except Exception as e:
            raise AppException(
                status_code=400,
                code="INVALID_IMPORT_FILE",
                message=f"Could not read the file: {str(e)}"
            )

        # Detect headers
        has_header = False
        lower_first = first_line.lower()
        header_keywords = ["smiles", "structure", "compound", "id", "name", "weight"]
        if any(kw in lower_first for kw in header_keywords):
            has_header = True
            
        parsed_rows = []
        
        try:
            with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
                if has_header:
                    reader = csv.reader(f, delimiter=delimiter)
                    headers = [h.strip() for h in next(reader)]
                    
                    smiles_idx = -1
                    cid_idx = -1
                    name_idx = -1
                    mw_idx = -1
                    logp_idx = -1
                    qed_idx = -1
                    tpsa_idx = -1
                    
                    req_smiles = request_data.get("smiles_column")
                    req_cid = request_data.get("compound_id_column")
                    req_name = request_data.get("name_column")
                    
                    for i, h in enumerate(headers):
                        lh = h.lower()
                        if req_smiles and h == req_smiles:
                            smiles_idx = i
                        elif smiles_idx == -1 and lh in ["smiles", "canonical_smiles", "canonicalsmiles", "mol_smiles", "structure"]:
                            smiles_idx = i
                            
                        if req_cid and h == req_cid:
                            cid_idx = i
                        elif cid_idx == -1 and lh in ["compound_id", "compoundid", "id", "molecule_id", "moleculeid"]:
                            cid_idx = i
                            
                        if req_name and h == req_name:
                            name_idx = i
                        elif name_idx == -1 and lh in ["name", "compound_name", "molecule_name"]:
                            name_idx = i
                            
                        if lh in ["mw", "molecular_weight", "molecularweight", "molecular_wt", "molwt"]:
                            mw_idx = i
                        elif lh in ["logp", "clogp", "log_p", "c_logp"]:
                            logp_idx = i
                        elif lh in ["qed"]:
                            qed_idx = i
                        elif lh in ["tpsa"]:
                            tpsa_idx = i
                            
                    # Fallback smiles index
                    if smiles_idx == -1:
                        for i, h in enumerate(headers):
                            if "smiles" in h.lower():
                                smiles_idx = i
                                break
                        if smiles_idx == -1:
                            smiles_idx = 0
                            
                    for row in reader:
                        if not row or len(row) <= smiles_idx:
                            continue
                        
                        smiles_val = row[smiles_idx].strip()
                        cid_val = row[cid_idx].strip() if (cid_idx != -1 and cid_idx < len(row)) else None
                        name_val = row[name_idx].strip() if (name_idx != -1 and name_idx < len(row)) else None
                        
                        mw_val = None
                        if mw_idx != -1 and mw_idx < len(row):
                            try:
                                mw_val = float(row[mw_idx])
                            except ValueError:
                                pass
                                
                        logp_val = None
                        if logp_idx != -1 and logp_idx < len(row):
                            try:
                                logp_val = float(row[logp_idx])
                            except ValueError:
                                pass
                                
                        qed_val = None
                        if qed_idx != -1 and qed_idx < len(row):
                            try:
                                qed_val = float(row[qed_idx])
                            except ValueError:
                                pass
                                
                        tpsa_val = None
                        if tpsa_idx != -1 and tpsa_idx < len(row):
                            try:
                                tpsa_val = float(row[tpsa_idx])
                            except ValueError:
                                pass
                                
                        parsed_rows.append({
                            "smiles": smiles_val,
                            "compound_id": cid_val,
                            "name": name_val,
                            "mw": mw_val,
                            "logp": logp_val,
                            "qed": qed_val,
                            "tpsa": tpsa_val
                        })
                else:
                    # Headerless SMILES file: SMILES COMPOUND_ID
                    f.seek(0)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split(delimiter) if delimiter != " " else line.split()
                        if not parts:
                            continue
                        
                        smiles_val = parts[0].strip()
                        cid_val = parts[1].strip() if len(parts) > 1 else None
                        parsed_rows.append({
                            "smiles": smiles_val,
                            "compound_id": cid_val,
                            "name": None,
                            "mw": None,
                            "logp": None,
                            "qed": None,
                            "tpsa": None
                        })
        except Exception as e:
            raise AppException(
                status_code=400,
                code="MOLECULE_IMPORT_FAILED",
                message=f"Error parsing file columns: {str(e)}"
            )

        if not parsed_rows:
            raise AppException(
                status_code=400,
                code="INVALID_IMPORT_FILE",
                message="No valid rows parsed from the scientific library file."
            )

        # Retrieve duplicate checker sets
        smiles_list = [row["smiles"] for row in parsed_rows if row["smiles"]]
        existing_smiles = await molecule_repository.get_existing_smiles_set(project_id, smiles_list)
        
        # Track duplicate compound IDs inside the DB
        max_suffix = await molecule_repository.get_max_compound_id_suffix(project_id)
        
        created_count = 0
        skipped_count = 0
        duplicate_count = 0
        invalid_count = 0
        
        batch_docs = []
        local_seen_smiles = set()
        local_seen_compound_ids = set()
        
        now = utc_now()
        
        for row in parsed_rows:
            smiles = row["smiles"]
            if not smiles:
                invalid_count += 1
                continue
                
            # Deduplicate SMILES
            if smiles in existing_smiles or smiles in local_seen_smiles:
                duplicate_count += 1
                continue
                
            # Assign compound_id
            compound_id = row["compound_id"]
            if not compound_id or compound_id in local_seen_compound_ids:
                max_suffix += 1
                compound_id = f"QDF-{max_suffix:06d}"
                
            local_seen_smiles.add(smiles)
            local_seen_compound_ids.add(compound_id)
            
            mol_doc = {
                "project_id": ObjectId(project_id),
                "workspace_id": ObjectId(workspace_id),
                "source_file_id": source_file_id,
                "compound_id": compound_id,
                "name": row.get("name"),
                "smiles": smiles,
                "inchi": None,
                "inchikey": None,
                "mw": row.get("mw"),
                "logp": row.get("logp"),
                "qed": row.get("qed"),
                "tpsa": row.get("tpsa"),
                "status": "uploaded",
                "source": "csv_import",
                "metadata": {},
                "created_by": ObjectId(user_id),
                "created_at": now,
                "updated_at": now
            }
            batch_docs.append(mol_doc)

        # Batch insertion
        if batch_docs:
            created_count = await molecule_repository.create_many_molecules(batch_docs)
            
        # Fetch the newly imported records to return as a sample
        sample_items = batch_docs[:10]
        
        # Re-fetch from DB or construct response items
        # For Phase 6 return, constructor map works perfectly
        from app.schemas.molecule import MoleculeResponse
        sample_responses = []
        for doc in sample_items:
            # Add fake _id for schema mapping if not already in document (insert_many updates it in place)
            if "_id" not in doc:
                doc["_id"] = ObjectId()
            sample_responses.append(MoleculeResponse.from_mongo(doc))

        return {
            "source_file_id": source_file_id,
            "created_count": created_count,
            "skipped_count": skipped_count,
            "duplicate_count": duplicate_count,
            "invalid_count": invalid_count,
            "items": sample_responses
        }

molecule_service = MoleculeService()
