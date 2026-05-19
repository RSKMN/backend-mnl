# Phase 17.5 — Backend Integration Smoke Test Suite

This document describes the backend integration smoke test suite, how to execute it, its features, and the API coverage details.

---

## 1. Overview & Goals

The backend smoke test suite (`tests/test_phase17_integration_smoke.py`) is designed to verify the entire core pipeline contract of the QuDrugForge backend APIs within a single, ultra-fast, mock-isolated test case.

### Key Guidelines Followed
1. **Mock-Isolated**: Relies on `tests.utils.mock_db.MockDatabase` (an in-memory MongoDB emulator) and an isolated local storage directory. It will **never** alter, drop, or query your production databases.
2. **Instant Compute**: Bypasses actual scientific engines (docking, quantum, molecular dynamics simulation) using built-in simulation flags, running the entire pipeline in under **1 second**.
3. **Robust Contracts**: Validates exact request and response structures (FastAPI/Pydantic schemas) for every major research, data, and report compilation endpoint.

---

## 2. Environment Configurations

No special environment variables are required to run the tests locally because the shared `tests/conftest.py` automatically configures safe defaults:
- `APP_ENV=test`
- `MONGODB_DATABASE=qudrugforge_test`
- `LOCAL_STORAGE_ROOT=./storage_test`
- `Q_AI_DRUG_ENABLED=false`

---

## 3. End-to-End Test Flow Covered

The suite executes the following sequential lifecycle steps:
1. **Auth & Identity**: Registers a new user (`POST /api/v1/auth/register`) and verifies login (`POST /api/v1/auth/login`), generating a clean test token.
2. **Workspace & Projects**: Lists workspaces (`GET /api/v1/workspaces`) and creates a new project (`POST /api/v1/projects`).
3. **File Management**: Uploads a ligands CSV library and target PDB structure file (`POST /api/v1/projects/{id}/files/upload`).
4. **Project Inputs**: Sets coordinates and custom sizes for the 3D binding site box (`PATCH /api/v1/projects/{id}/inputs/binding-site`).
5. **Molecules Pipeline**: Imports compounds from the uploaded ligands CSV (`POST /api/v1/projects/{id}/molecules/import`) and lists active candidates (`GET /api/v1/projects/{id}/molecules`).
6. **Target Verification**: Configures target metadata and associates the structural file (`POST /api/v1/projects/{id}/targets`).
7. **Experiment Queue**: Launches a simulated virtual screen docking run (`POST /api/v1/projects/{id}/experiments`).
8. **Pipeline Results**: Queries list and filter endpoints across all primary disciplines, guaranteeing correct schema returns:
   - Docking: `GET /api/v1/projects/{id}/docking/results`
   - GNINA: `GET /api/v1/projects/{id}/gnina/results`
   - Quantum Mechanics: `GET /api/v1/projects/{id}/quantum/descriptors`
   - ADMET Profiling: `GET /api/v1/projects/{id}/admet/results`
   - Molecular Dynamics: `GET /api/v1/projects/{id}/simulations/results`
9. **Visual Analytics**: Verifies the chemical-space projection matrix (`GET /api/v1/projects/{id}/chemical-space`).
10. **Scientific Search**: Validates similarity and Tanimoto coefficient sorting (`POST /api/v1/projects/{id}/similarity/search`).
11. **Report Lifecycle**: Creates a report draft (`POST /api/v1/projects/{id}/reports`), compiles CSV, HTML, and PDF formats (`POST /api/v1/projects/{id}/reports/{id}/generate`), and verifies files (`GET /api/v1/projects/{id}/reports/{id}/files`).
12. **File Downloads**: Downloads compile artifacts to assert correct HTTP transmission (`GET /api/v1/files/{file_id}/download`).

---

## 4. How To Execute

To run the integration smoke test suite independently:

```bash
# Navigate to the backend directory
cd backend-mnl/qudrugforge-backend

# Run the test suite with verbose output
pytest tests/test_phase17_integration_smoke.py -v
```

### Successful Run Example Output
```bash
$ pytest tests/test_phase17_integration_smoke.py -v
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-8.4.2, pluggy-1.5.0
cachedir: .pytest_cache
rootdir: E:\rskmn\Npersonal\quinfosys\drug_discovery_research\work\mnl\backend-mnl\qudrugforge-backend
configfile: pytest.ini
plugins: anyio-4.10.0, asyncio-1.3.0
asyncio: mode=Mode.AUTO

collected 1 item

tests/test_phase17_integration_smoke.py::test_full_backend_real_api_smoke_flow PASSED [100%]

======================== 1 passed in 0.56s ========================
```
