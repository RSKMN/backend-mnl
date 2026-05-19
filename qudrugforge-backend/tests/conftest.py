import sys
import os
import shutil
import asyncio
import pytest
from unittest.mock import AsyncMock

# Ensure the root of qudrugforge-backend is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment variables BEFORE importing settings or database
os.environ["APP_ENV"] = "test"
os.environ["MONGODB_DATABASE"] = "qudrugforge_test"
os.environ["LOCAL_STORAGE_ROOT"] = "./storage_test"
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["Q_AI_DRUG_ENABLED"] = "false"
os.environ["Q_AI_DRUG_OUTPUT_ROOT"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_q_ai_drug_outputs")
os.environ["Q_AI_DRUG_IMPORT_ALLOW_ABSOLUTE_PATHS"] = "true"
os.environ["ENABLE_DEV_JOB_SIMULATION"] = "true"
os.environ["JOB_SIMULATION_STEP_SECONDS"] = "0"

# Import our custom in-memory MongoDB/Motor emulator
from tests.utils.mock_db import MockDatabase
MOCK_DATABASE = MockDatabase()

# Globally patch the database module before other imports occur
import app.core.database
app.core.database.get_database = lambda: MOCK_DATABASE
app.core.database.database = MOCK_DATABASE
app.core.database.connect_to_mongo = AsyncMock()
app.core.database.close_mongo_connection = AsyncMock()

from app.core.config import settings
from app.core.database import ensure_auth_indexes
from app.main import app
from httpx import AsyncClient, ASGITransport

@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped asyncio event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def test_settings():
    """Return isolated test settings."""
    return settings

@pytest.fixture(scope="session")
def test_app():
    """Return the FastAPI test application instance."""
    return app

@pytest.fixture(scope="session")
def test_db():
    """Expose the active patched MongoDB mock database context."""
    return MOCK_DATABASE

@pytest.fixture(scope="session")
async def async_client(test_app):
    """Provide a lifespan-managed HTTPX AsyncClient using ASGITransport."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac

@pytest.fixture(autouse=True)
async def clean_database(test_db):
    """Clean all database collections before each test run to ensure strict isolation."""
    collections = await test_db.list_collection_names()
    for col in collections:
        await test_db[col].drop()
    await ensure_auth_indexes()

@pytest.fixture(scope="session")
def test_storage_root():
    """Expose and initialize the isolated local test storage path."""
    root = settings.LOCAL_STORAGE_ROOT
    if not os.path.exists(root):
        os.makedirs(root)
    yield root
    # Cleanup storage directory on test suite completion
    if os.path.exists(root):
        try:
            shutil.rmtree(root)
        except Exception:
            pass

@pytest.fixture(autouse=True)
def clean_storage(test_storage_root):
    """Wipe all storage folders inside test storage between tests."""
    for item in os.listdir(test_storage_root):
        item_path = os.path.join(test_storage_root, item)
        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
        except Exception:
            pass

@pytest.fixture
async def registered_user(async_client):
    """Register a fresh user using the public API and return authorization information."""
    payload = {
        "email": "testuser@example.com",
        "password": "SecurePassword123!",
        "full_name": "Test User",
        "workspace_name": "Test Workspace"
    }
    response = await async_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 200, f"Register failed: {response.text}"
    return response.json()["data"]

@pytest.fixture
def auth_token(registered_user):
    """Extract and return JWT access token for the registered user."""
    return registered_user["access_token"]

@pytest.fixture
def auth_headers(auth_token):
    """Expose HTTP Authorization headers populated with the bearer JWT."""
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.fixture
def workspace(registered_user):
    """Expose the workspace info returned upon user registration."""
    return registered_user["workspace"]

@pytest.fixture
async def project(async_client, auth_headers, workspace):
    """Create a test project within the registered user's workspace."""
    payload = {
        "workspace_id": workspace["id"],
        "name": "Test Project",
        "description": "Oncology target discovery project",
        "disease_type": "Cancer",
        "cancer_type": "NSCLC"
    }
    response = await async_client.post("/api/v1/projects", json=payload, headers=auth_headers)
    assert response.status_code == 200, f"Project creation failed: {response.text}"
    return response.json()["data"]

@pytest.fixture
async def project_inputs(async_client, auth_headers, project):
    """Fetch the project inputs record for the created test project."""
    response = await async_client.get(f"/api/v1/projects/{project['id']}/inputs", headers=auth_headers)
    assert response.status_code == 200, f"Failed fetching project inputs: {response.text}"
    return response.json()["data"]

@pytest.fixture
async def uploaded_fasta_file(async_client, auth_headers, project):
    """Upload a mock FASTA file to the test project and return its metadata."""
    fasta_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_files", "protein.fasta")
    with open(fasta_path, "rb") as f:
        response = await async_client.post(
            f"/api/v1/projects/{project['id']}/files/upload",
            files={"file": ("protein.fasta", f, "application/octet-stream")},
            data={"file_type": "protein_fasta", "source_module": "project_inputs"},
            headers=auth_headers
        )
    assert response.status_code == 200, f"FASTA upload failed: {response.text}"
    return response.json()["data"]["file"]

@pytest.fixture
async def uploaded_pdb_file(async_client, auth_headers, project):
    """Upload a mock PDB file to the test project and return its metadata."""
    pdb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_files", "protein.pdb")
    with open(pdb_path, "rb") as f:
        response = await async_client.post(
            f"/api/v1/projects/{project['id']}/files/upload",
            files={"file": ("protein.pdb", f, "application/octet-stream")},
            data={"file_type": "protein_structure", "source_module": "project_inputs"},
            headers=auth_headers
        )
    assert response.status_code == 200, f"PDB upload failed: {response.text}"
    return response.json()["data"]["file"]

@pytest.fixture
async def uploaded_ligands_csv(async_client, auth_headers, project):
    """Upload a mock ligands CSV library to the test project and return its metadata."""
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_files", "ligands.csv")
    with open(csv_path, "rb") as f:
        response = await async_client.post(
            f"/api/v1/projects/{project['id']}/files/upload",
            files={"file": ("ligands.csv", f, "text/csv")},
            data={"file_type": "compound_library", "source_module": "project_inputs"},
            headers=auth_headers
        )
    assert response.status_code == 200, f"CSV library upload failed: {response.text}"
    return response.json()["data"]["file"]

@pytest.fixture
def q_ai_drug_output_root():
    """Return the directory containing pre-built Q-AI-Drug simulation run folders."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "sample_q_ai_drug_outputs")
