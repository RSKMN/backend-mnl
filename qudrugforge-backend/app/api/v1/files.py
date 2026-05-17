import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, Path
from fastapi.responses import FileResponse

from app.services.file_service import file_service
from app.schemas.file import FileMetadataResponse, FileListResponse
from app.core.dependencies import get_current_active_user
from app.core.exceptions import AppException

logger = logging.getLogger("qudrugforge-files-api")
router = APIRouter(tags=["Files"])

@router.post("/projects/{project_id}/files/upload")
async def upload_file(
    project_id: str = Path(...),
    file: UploadFile = File(...),
    file_type: Optional[str] = Form(None),
    source_module: Optional[str] = Form(None),
    metadata: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    
    metadata_dict = {}
    if metadata:
        try:
            metadata_dict = json.loads(metadata)
        except Exception:
            raise AppException(
                status_code=400,
                code="VALIDATION_ERROR",
                message="metadata must be a valid JSON string"
            )
            
    created_metadata = await file_service.upload_file(
        project_id=project_id,
        file=file,
        file_type=file_type,
        source_module=source_module,
        metadata=metadata_dict,
        user_id=user_id
    )
    
    serialized = FileMetadataResponse.from_mongo(created_metadata).model_dump()
    
    return {
        "success": True,
        "data": {
            "file": serialized
        },
        "message": "File uploaded successfully"
    }

@router.get("/projects/{project_id}/files")
async def list_files(
    project_id: str = Path(...),
    file_type: Optional[str] = Query(None),
    source_module: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    
    items, total = await file_service.list_files(
        project_id=project_id,
        file_type=file_type,
        source_module=source_module,
        skip=offset,
        limit=limit,
        user_id=user_id
    )
    
    serialized_items = [FileMetadataResponse.from_mongo(item).model_dump() for item in items]
    
    return {
        "success": True,
        "data": {
            "items": serialized_items,
            "total": total,
            "limit": limit,
            "offset": offset
        },
        "message": "Files fetched"
    }

@router.get("/files/{file_id}")
async def get_file_detail(
    file_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    
    metadata = await file_service.get_file_detail(file_id, user_id)
    serialized = FileMetadataResponse.from_mongo(metadata).model_dump()
    
    return {
        "success": True,
        "data": serialized,
        "message": "File fetched successfully"
    }

@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    
    file_path, original_filename = await file_service.get_file_download_path(file_id, user_id)
    
    return FileResponse(
        path=file_path,
        filename=original_filename,
        media_type="application/octet-stream"
    )

@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str = Path(...),
    current_user: dict = Depends(get_current_active_user)
):
    user_id = str(current_user["_id"])
    
    await file_service.delete_file(file_id, user_id)
    
    return {
        "success": True,
        "message": "File deleted successfully"
    }
