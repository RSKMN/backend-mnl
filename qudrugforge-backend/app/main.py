import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, status, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.database import connect_to_mongo, close_mongo_connection, ensure_auth_indexes
from app.core.exceptions import AppException, app_exception_handler, generic_exception_handler, DomainError, domain_exception_handler
from app.core.rate_limit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.middleware import SecurityHeadersMiddleware
from app.core.metrics_middleware import MetricsMiddleware
from app.api.v1.router import api_v1_router
from app.api.v1.health import health_check
from app.api.v1.metrics import router as metrics_router

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

# 4. Middleware & CORS Setup
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MetricsMiddleware)

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
app.add_exception_handler(DomainError, domain_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# 6. Mount Master Routing V1
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)
app.include_router(metrics_router, prefix="/metrics", tags=["Metrics"])

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
async def root_health(response: Response):
    """
    Exposes a root-level health indicator mapped to the core health sub-router logic.
    """
    return await health_check(response)
