from abc import ABC, abstractmethod
from fastapi import UploadFile

class StorageProvider(ABC):
    """
    Abstract base class defining the contract for physical scientific file storage providers.
    Ensures seamless migration to cloud storage without API changes.
    """
    
    @abstractmethod
    async def save_file(self, file: UploadFile, destination_path: str) -> dict:
        """
        Saves an uploaded file to the specified destination path.
        Returns a dict containing file properties like size_bytes, checksum, etc.
        """
        pass

    @abstractmethod
    async def get_file_path(self, stored_path: str) -> str:
        """
        Resolves the stored path to a local path (for downloads/processing).
        """
        pass

    @abstractmethod
    async def delete_file(self, stored_path: str) -> bool:
        """
        Deletes a file from physical storage.
        """
        pass

    @abstractmethod
    async def exists(self, stored_path: str) -> bool:
        """
        Checks if a file exists in the physical storage.
        """
        pass

    @abstractmethod
    def ensure_directories(self) -> None:
        """
        Creates necessary storage folders on startup.
        """
        pass
