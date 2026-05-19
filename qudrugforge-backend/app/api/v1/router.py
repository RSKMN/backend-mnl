from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.system import router as system_router
from app.api.v1.auth import router as auth_router
from app.api.v1.workspaces import router as workspaces_router
from app.api.v1.projects import router as projects_router
from app.api.v1.files import router as files_router
from app.api.v1.targets import router as targets_router
from app.api.v1.molecules import router as molecules_router
from app.api.v1.q_ai_drug import router as q_ai_drug_router
from app.api.v1.artifact_import import router as artifact_import_router
from app.api.v1.experiments import router as experiments_router
from app.api.v1.docking import router as docking_router
from app.api.v1.gnina import router as gnina_router
from app.api.v1.quantum import router as quantum_router
from app.api.v1.simulations import router as simulations_router
from app.api.v1.admet import router as admet_router
from app.api.v1.viewer import router as viewer_router
from app.api.v1.chemical_space import router as chemical_space_router
from app.api.v1.similarity import router as similarity_router
from app.api.v1.reports import router as reports_router
from app.api.v1.pipeline import router as pipeline_router

api_v1_router = APIRouter()

# Register sub-routing components
api_v1_router.include_router(health_router)
api_v1_router.include_router(system_router)
api_v1_router.include_router(auth_router, prefix="/auth")
api_v1_router.include_router(workspaces_router, prefix="/workspaces")
api_v1_router.include_router(projects_router, prefix="/projects")
api_v1_router.include_router(files_router)
api_v1_router.include_router(targets_router)
api_v1_router.include_router(molecules_router)
api_v1_router.include_router(q_ai_drug_router)
api_v1_router.include_router(experiments_router)
api_v1_router.include_router(docking_router)
api_v1_router.include_router(gnina_router)
api_v1_router.include_router(quantum_router)
api_v1_router.include_router(simulations_router)
api_v1_router.include_router(admet_router)
api_v1_router.include_router(artifact_import_router)
api_v1_router.include_router(viewer_router)
api_v1_router.include_router(chemical_space_router)
api_v1_router.include_router(similarity_router)
api_v1_router.include_router(reports_router)
api_v1_router.include_router(pipeline_router)


