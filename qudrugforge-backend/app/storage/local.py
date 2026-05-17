import os
import hashlib
import logging
from pathlib import Path
from fastapi import UploadFile
from app.storage.base import StorageProvider
from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger("qudrugforge-storage-local")

class LocalStorageProvider(StorageProvider):
    """
    Local filesystem storage provider implementation.
    Manages scientific structure files on the local host drive during development.
    """
    
    def __init__(self, root_dir: str = None):
        self.root_path = Path(root_dir or settings.LOCAL_STORAGE_ROOT).resolve()
        logger.info(f"Initialized LocalStorageProvider pointing to: {self.root_path}")
        
    def _resolve_secure_path(self, target_path: str) -> Path:
        """
        Resolves a safe absolute path, preventing path traversal vulnerabilities 
        by verifying the target resides inside the local storage root.
        """
        try:
            resolved_absolute = (self.root_path / target_path).resolve()
            # Enforce that the target resides inside our configured root path
            if not str(resolved_absolute).startswith(str(self.root_path)):
                raise AppException(
                    status_code=400,
                    code="FILE_ACCESS_DENIED",
                    message="Directory traversal attempt detected."
                )
            return resolved_absolute
        except AppException as e:
            raise e
        except Exception as e:
            raise AppException(
                status_code=400,
                code="VALIDATION_ERROR",
                message=f"Invalid file path: {str(e)}"
            )

    async def save_file(self, file: UploadFile, destination_path: str) -> dict:
        """
        Saves an uploaded file to the local directory.
        Calculates SHA256 checksum and size in bytes.
        Enforces MAX_UPLOAD_SIZE_MB limit.
        """
        absolute_path = self._resolve_secure_path(destination_path)
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        
        try:
            # Ensure parent directories are created
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Reset seek position to beginning
            await file.seek(0)
            
            size_bytes = 0
            sha256 = hashlib.sha256()
            
            # Write stream in chunks
            with open(absolute_path, "wb") as f:
                while chunk := await file.read(1024 * 64): # 64KB chunks
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        f.close()
                        if absolute_path.exists():
                            absolute_path.unlink()
                        raise AppException(
                            status_code=413,
                            code="VALIDATION_ERROR",
                            message=f"File exceeds maximum allowed upload size of {settings.MAX_UPLOAD_SIZE_MB}MB."
                        )
                    f.write(chunk)
                    sha256.update(chunk)
            
            checksum = sha256.hexdigest()
            logger.debug(f"Successfully wrote upload file to local disk: {absolute_path}")
            
            return {
                "size_bytes": size_bytes,
                "checksum": checksum,
                "local_path": destination_path
            }
        except AppException as e:
            raise e
        except Exception as e:
            logger.error(f"Failed to write file to local disk: {str(e)}")
            if absolute_path.exists():
                try:
                    absolute_path.unlink()
                except Exception:
                    pass
            raise AppException(
                status_code=500,
                code="FILE_UPLOAD_FAILED",
                message=f"An error occurred writing file to local disk: {str(e)}"
            )


    async def get_file_path(self, stored_path: str) -> str:
        """
        Resolves stored path to absolute local path.
        """
        absolute_path = self._resolve_secure_path(stored_path)
        if not absolute_path.exists() or not absolute_path.is_file():
            raise AppException(
                status_code=404,
                code="FILE_MISSING_ON_STORAGE",
                message=f"File '{stored_path}' is missing on physical storage."
            )
        return str(absolute_path)

    async def delete_file(self, stored_path: str) -> bool:
        """
        Deletes a file from the local directory.
        """
        try:
            absolute_path = self._resolve_secure_path(stored_path)
            
            if not absolute_path.exists() or not absolute_path.is_file():
                logger.warning(f"Deletion target file does not exist: {stored_path}")
                return False
                
            absolute_path.unlink()
            logger.debug(f"Deleted file from local storage: {absolute_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file from local disk: {str(e)}")
            raise AppException(
                status_code=500,
                code="FILE_DELETE_FAILED",
                message=f"Could not remove local file: {str(e)}"
            )

    async def exists(self, stored_path: str) -> bool:
        """
        Checks if a file exists on the local filesystem.
        """
        try:
            absolute_path = self._resolve_secure_path(stored_path)
            return absolute_path.exists() and absolute_path.is_file()
        except Exception:
            return False

    def ensure_directories(self) -> None:
        """
        Creates storage directories under the root folder if they are missing.
        """
        for subdir in ["uploads", "artifacts", "reports", "temp"]:
            dir_path = self.root_path / subdir
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured storage directory exists: {dir_path}")
