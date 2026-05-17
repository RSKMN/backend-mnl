# QuDrugForge™ Phase 0 Acceptance Checklist

This verification checklist outlines the requirements to be met for Phase 0 (Repository & Architectural Setup) of the QuDrugForge™ Backend.

---

## Repository Foundation & Directory Structure
- [ ] **Backend Project Root**: The base project directory `qudrugforge-backend/` is correctly provisioned.
- [ ] **FastAPI Core Module Directory (`app/`)**: Created with standard core and structure packages:
  - [ ] `app/main.py`
  - [ ] `app/core/` (`config.py`, `database.py`, `security.py`, `logging.py`, `exceptions.py`)
  - [ ] `app/api/` (`v1/router.py`)
  - [ ] `app/schemas/`
  - [ ] `app/models/`
  - [ ] `app/repositories/`
  - [ ] `app/services/`
  - [ ] `app/storage/` (`base.py`, `local.py`, `service.py`)
  - [ ] `app/integrations/` (`q_ai_drug_client.py`)
  - [ ] `app/utils/`
- [ ] **Tests Module Directory (`tests/`)**: Created with `__init__.py` to support future automated validation pipelines.
- [ ] **Scripts Module Directory (`scripts/`)**: Created with `.gitkeep` to house utility orchestration tools.
- [ ] **Physical Storage Folders (`storage/`)**: Created with appropriate subfolders and `.gitkeep` placeholders to ensure clean structure preservation in version control:
  - [ ] `storage/uploads/`
  - [ ] `storage/artifacts/`
  - [ ] `storage/reports/`
  - [ ] `storage/temp/`

---

## Configuration & Environments
- [ ] **Environment Template (`.env.example`)**: Loaded with appropriate default configurations (App environments, API prefix, MongoDB cluster URIs, Storage root, JWT token lifetimes, external q-ai-drug addresses, and CORS limits).
- [ ] **Dependency Registry (`requirements.txt`)**: Provisioned with only the core dependencies needed (FastAPI, Uvicorn, Motor, Pydantic settings, Cryptography drivers, HTTPX, PyTest, etc.).
- [ ] **Version Control Filters (`.gitignore`)**: Provisioned to filter cache files (`__pycache__`), virtual environments (`.venv`), active credentials (`.env`), and dynamic storage content, while explicitly preserving folder headers (`.gitkeep`).

---

## Architectural & Planning Documentation
- [ ] **System Architecture Plan (`docs/architecture.md`)**: Complete overview detailing backend separations, external compute relationships, and storage driver designs.
- [ ] **Database Schema Plan (`docs/database_plan.md`)**: Detailed collection design specifications mapping users, workspaces, projects, chemical targets, docking structures, quantum QM results, ADMET risks, audit logs, and copilot dialogs.
- [ ] **Storage Strategy Plan (`docs/storage_plan.md`)**: Guidelines describing the database-to-filesystem storage segregation, folder duties, and future multi-cloud bucket migrations.
- [ ] **Compute Integration Plan (`docs/q_ai_drug_integration_plan.md`)**: Description of integration methods, API wrappers, and the ingestion and processing mapping for external `q-ai-drug` files.
- [ ] **Frontend Route Map (`docs/frontend_backend_mapping.md`)**: Complete indexing of frontend pages/actions with their targeted backend API endpoints.
- [ ] **Developer Introduction Guide (`README.md`)**: General setup, execution steps, and design system instructions.

---

## Minimal Code Implementations
- [ ] **Application Entrypoint (`app/main.py`)**: Features a clean FastAPI initialization containing simple GET `/` and GET `/health` routes with no dynamic compute, authentication, or database operations.
- [ ] **Module Placeholders**: All other subdirectories are set up with empty `__init__.py` or module files containing comments clarifying upcoming implementations.

---

## Developer Evaluation
- [ ] **Portability**: A new developer can clone or check out this repository, configure their environment, and immediately run the basic webserver with minimal effort or instructions.
