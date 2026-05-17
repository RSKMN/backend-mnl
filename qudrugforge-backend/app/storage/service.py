import logging
from app.core.config import settings
from app.storage.base import StorageProvider
from app.storage.local import LocalStorageProvider

logger = logging.getLogger("qudrugforge-storage-service")

class StorageService:
    """
    System-wide Orchestrator Service managing the active file storage provider.
    Resolves the physical driver based on environment variables.
    """
    
    def __init__(self):
        self.provider = self._resolve_provider()
        
    def _resolve_provider(self) -> StorageProvider:
        provider_name = settings.STORAGE_PROVIDER.lower()
        
        if provider_name == "local":
            logger.info("Initializing 'local' filesystem storage engine.")
            return LocalStorageProvider()
        else:
            # Multi-cloud driver registrations (S3, R2, Azure) will register here.
            logger.warning(
                f"Configured storage provider '{provider_name}' is not yet implemented. "
                "Defaulting to 'local' filesystem engine for platform stability."
            )
            return LocalStorageProvider()

    def get_provider(self) -> StorageProvider:
        """
        Returns the active, concrete storage driver.
        """
        return self.provider

# Global single service instance to run unified storage actions across all routers/endpoints
storage_service = StorageService()
