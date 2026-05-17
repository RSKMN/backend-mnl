import os
import re
import uuid
import logging
from bson import ObjectId
from typing import Optional, List, Tuple
from fastapi import UploadFile

from app.repositories.file_metadata_repository import file_metadata_repository
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.storage.service import storage_service
from app.core.config import settings
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-file-service")

class FileService:
    ALLOWED_EXTENSIONS = {
        '.fasta', '.fa', '.pdb', '.cif', '.mmcif', '.sdf', '.smi', '.csv', '.tsv', '.json', '.pdf', '.txt'
    }

    ALLOWED_FILE_TYPES = {
        'protein_fasta', 'protein_structure', 'alphafold_structure', 'reference_ligand',
        'compound_library', 'assay_data', 'admet_data', 'tumor_mutation', 'rna_ihc',
        'organoid_response', 'generated_report', 'docking_pose', 'gnina_pose',
        'quantum_descriptor', 'simulation_trajectory', 'other',
        'generated_candidates', 'filtered_candidates', 'docking_results',
        'gnina_results', 'quantum_score', 'simulation_result', 'q_ai_drug_artifact'
    }

    async def check_workspace_access(self, workspace_id: str, user_id: str) -> dict:
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace"
            )
        return membership

    async def upload_file(
        self,
        project_id: str,
        file: UploadFile,
        file_type: Optional[str],
        source_module: Optional[str],
        metadata: Optional[dict],
        user_id: str
    ) -> dict:
        # 1. Fetch project and validate
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found"
            )

        # 2. Validate workspace access
        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        # 3. Validate file extension
        filename = file.filename or "unnamed_file"
        _, ext = os.path.splitext(filename.lower())
        if ext not in self.ALLOWED_EXTENSIONS:
            raise AppException(
                status_code=400,
                code="UNSUPPORTED_FILE_TYPE",
                message=f"File extension '{ext}' is not supported. Supported: {list(self.ALLOWED_EXTENSIONS)}"
            )

        # 4. Infer/Validate file_type
        if file_type:
            if file_type not in self.ALLOWED_FILE_TYPES:
                raise AppException(
                    status_code=400,
                    code="INVALID_FILE_TYPE",
                    message=f"Invalid file_type '{file_type}'. Allowed: {list(self.ALLOWED_FILE_TYPES)}"
                )
        else:
            if ext in ['.fasta', '.fa']:
                file_type = 'protein_fasta'
            elif ext in ['.pdb', '.cif', '.mmcif']:
                file_type = 'protein_structure'
            elif ext in ['.sdf', '.smi']:
                file_type = 'compound_library'
            elif ext in ['.csv', '.tsv']:
                file_type = 'compound_library'
            elif ext in ['.pdf']:
                file_type = 'generated_report'
            else:
                file_type = 'other'

        # 5. Generate secure metadata fields
        file_id = str(uuid.uuid4())
        safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        safe_filename = re.sub(r'_+', '_', safe_filename)
        stored_filename = f"{file_id}_{safe_filename}"

        destination_path = f"uploads/{workspace_id}/{project_id}/{stored_filename}"

        # 6. Save using concrete storage provider
        provider = storage_service.get_provider()
        save_result = await provider.save_file(file, destination_path)

        # 7. Create MongoDB record
        now = utc_now()
        doc = {
            "file_id": file_id,
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(workspace_id),
            "uploaded_by": ObjectId(user_id),
            "original_filename": filename,
            "stored_filename": stored_filename,
            "file_type": file_type,
            "mime_type": file.content_type or "application/octet-stream",
            "local_path": save_result["local_path"],
            "size_bytes": save_result["size_bytes"],
            "checksum": save_result["checksum"],
            "source_module": source_module or "project_inputs",
            "kind": "uploaded",
            "artifact_type": ext.lstrip("."),
            "linked_experiment_id": None,
            "storage_provider": settings.STORAGE_PROVIDER,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now
        }

        created = await file_metadata_repository.create_metadata(doc)
        return created

    async def list_files(
        self,
        project_id: str,
        file_type: Optional[str],
        source_module: Optional[str],
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

        workspace_id = str(project["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        items, total = await file_metadata_repository.list_metadata_by_project(
            project_id=project_id,
            file_type=file_type,
            source_module=source_module,
            skip=skip,
            limit=limit
        )
        return items, total

    async def get_file_detail(self, file_id: str, user_id: str) -> dict:
        metadata = await file_metadata_repository.get_metadata_by_file_id(file_id)
        if not metadata:
            raise AppException(
                status_code=404,
                code="FILE_NOT_FOUND",
                message="File metadata not found"
            )

        workspace_id = str(metadata["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        return metadata

    async def get_file_download_path(self, file_id: str, user_id: str) -> Tuple[str, str]:
        metadata = await file_metadata_repository.get_metadata_by_file_id(file_id)
        if not metadata:
            raise AppException(
                status_code=404,
                code="FILE_NOT_FOUND",
                message="File metadata not found"
            )

        workspace_id = str(metadata["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        provider = storage_service.get_provider()
        if not await provider.exists(metadata["local_path"]):
            raise AppException(
                status_code=404,
                code="FILE_MISSING_ON_STORAGE",
                message="File is missing on physical storage."
            )

        resolved_path = await provider.get_file_path(metadata["local_path"])
        return resolved_path, metadata["original_filename"]

    async def delete_file(self, file_id: str, user_id: str) -> bool:
        metadata = await file_metadata_repository.get_metadata_by_file_id(file_id)
        if not metadata:
            raise AppException(
                status_code=404,
                code="FILE_NOT_FOUND",
                message="File metadata not found"
            )

        workspace_id = str(metadata["workspace_id"])
        await self.check_workspace_access(workspace_id, user_id)

        provider = storage_service.get_provider()
        
        # Safely delete local file (do not block DB delete if missing)
        try:
            await provider.delete_file(metadata["local_path"])
        except Exception as e:
            logger.warning(f"Could not delete physical file: {str(e)}")

        await file_metadata_repository.delete_metadata_by_file_id(file_id)
        return True

file_service = FileService()
