import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.database import connect_to_mongo, close_mongo_connection, ensure_auth_indexes
from app.core.exceptions import AppException, app_exception_handler, generic_exception_handler, validation_exception_handler
from fastapi.exceptions import RequestValidationError
from app.api.v1.router import api_v1_router
from app.api.v1.health import health_check

# 1. Setup python logging formats
configure_logging()
logger = logging.getLogger("qudrugforge-main")

# 2. Application Startup & Shutdown lifecycle orchestrator
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    logger.info("Initializing QuDrugForge platform backend...")
    
    # Create local storage directories if missing
    try:
        from app.storage.service import storage_service
        storage_service.get_provider().ensure_directories()
    except Exception as e:
        logger.error(f"Failed to ensure storage directories: {e}")
        
    await connect_to_mongo()
    await ensure_auth_indexes()
    yield
    # Shutdown tasks
    logger.info("Teardown QuDrugForge platform backend...")
    await close_mongo_connection()


# 3. Instantiate FastAPI application
app = FastAPI(
    title="QuDrugForge Backend",
    description="Quantum AI Drug Discovery Platform Application Backend - Phase 1 Foundation",
    version="1.0.0-phase1",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# 4. CORS Setup
origins = settings.cors_origins_list
logger.info(f"CORS origins configured: {origins}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Global custom exceptions mapping
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# 6. Mount Master Routing V1
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

# 7. Root API Entrypoints
@app.get("/", tags=["General"])
async def root():
    """
    Root endpoint serving basic service identifiers.
    """
    return {
        "service": "QuDrugForge Backend",
        "status": "running",
        "docs": "/docs",
        "api_prefix": settings.API_V1_PREFIX
    }

@app.get("/health", tags=["General"])
async def root_health():
    """
    Exposes a root-level health indicator mapped to the core health sub-router logic.
    """
    return await health_check()
