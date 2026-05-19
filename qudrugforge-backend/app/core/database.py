import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

logger = logging.getLogger("qudrugforge-database")

# Global driver container variables
mongodb_client: Optional[AsyncIOMotorClient] = None
database = None

async def connect_to_mongo():
    """
    Initializes a new Motor Async MongoDB client connection pool.
    Verifies connection by executing a diagnostic admin command ping.
    """
    global mongodb_client, database
    logger.info(f"Attempting connection to MongoDB database: {settings.MONGODB_DATABASE}...")
    
    try:
        # Instantiate Async client with a short timeout to prevent startup hangs
        mongodb_client = AsyncIOMotorClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=3000
        )
        database = mongodb_client[settings.MONGODB_DATABASE]
        
        # Diagnostics test command ping
        await mongodb_client.admin.command("ping")
        logger.info("Successfully connected and pinged MongoDB cluster.")
    except Exception as e:
        logger.error(f"MongoDB connection handshake failed: {str(e)}")
        # Graceful fallback in development environment
        if settings.APP_ENV == "development":
            logger.warning(
                "Platform starting without active MongoDB connection (Development grace mode)."
            )
            # Retain None references so health routers report disconnected state
            mongodb_client = None
            database = None
        else:
            # Raise startup crash exception in production environments
            raise e

async def close_mongo_connection():
    """
    Closes client connections cleanly on application teardown events.
    """
    global mongodb_client, database
    if mongodb_client is not None:
        logger.info("Closing MongoDB connections...")
        mongodb_client.close()
        mongodb_client = None
        database = None
        logger.info("MongoDB connection closed.")

# Globally shared fallback mock database instance for offline development runs
_fallback_mock_database = None

def get_database():
    """
    Returns active database context. Raises runtime exception if database isn't initialized.
    """
    global database, _fallback_mock_database
    if database is None:
        if settings.APP_ENV == "development":
            if _fallback_mock_database is None:
                try:
                    from tests.utils.mock_db import MockDatabase
                    _fallback_mock_database = MockDatabase()
                    logger.warning("Active MongoDB is disconnected. Using fallback high-fidelity MockDatabase for development.")
                except ImportError:
                    logger.warning("Could not load high-fidelity MockDatabase fallback from tests.")
            if _fallback_mock_database is not None:
                return _fallback_mock_database
        raise RuntimeError("Database pool not initialized. Call connect_to_mongo first.")
    return database

async def ensure_auth_indexes():
    global database
    if database is None:
        return
        
    try:
        import pymongo
        users = database["users"]
        await users.create_index("email", unique=True)
        
        workspaces = database["workspaces"]
        await workspaces.create_index("slug", unique=True)
        
        members = database["workspace_members"]
        await members.create_index("user_id")
        await members.create_index("workspace_id")
        await members.create_index([("workspace_id", pymongo.ASCENDING), ("user_id", pymongo.ASCENDING)], unique=True)
        
        # Projects Indexes
        projects = database["projects"]
        await projects.create_index("workspace_id")
        await projects.create_index("created_by")
        await projects.create_index("status")
        await projects.create_index([("workspace_id", pymongo.ASCENDING), ("slug", pymongo.ASCENDING)], unique=True)
        
        # Project Inputs Indexes
        project_inputs = database["project_inputs"]
        await project_inputs.create_index("project_id", unique=True)
        await project_inputs.create_index("workspace_id")
        
        # Files Indexes
        files = database["files"]
        await files.create_index("file_id", unique=True)
        await files.create_index("project_id")
        await files.create_index("workspace_id")
        await files.create_index("uploaded_by")
        await files.create_index("file_type")
        await files.create_index("source_module")
        await files.create_index("created_at")

        # Target and Molecule Indexes
        from app.repositories.target_repository import target_repository
        from app.repositories.molecule_repository import molecule_repository
        from app.repositories.report_repository import report_repository
        await target_repository.ensure_indexes()
        await molecule_repository.ensure_indexes()
        await report_repository.ensure_indexes()

        logger.info(
            "Auth, project, project input, files, targets, molecules, and reports indexes ensured."
        )
    except Exception as e:
        logger.error(f"Failed to ensure database indexes: {e}")
