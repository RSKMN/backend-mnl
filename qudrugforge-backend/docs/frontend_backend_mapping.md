# QuDrugForge™ Frontend-to-Backend API Contract Mapping

This document provides a detailed index mapping frontend interface modules/views directly to backend FastAPI route signatures.

---

## 1. Authentication & Workspace Governance

| Frontend Interface View | User Interaction Context | Backend API Endpoint Signature |
| :--- | :--- | :--- |
| `/login` | User authentication intake | `POST /api/v1/auth/login` |
| `/register` | New account provisioning | `POST /api/v1/auth/register` |
| &mdash; | Session check / user info load | `GET /api/v1/auth/me` |
| &mdash; | Token rotation | `POST /api/v1/auth/refresh` |
| &mdash; | Session invalidation | `POST /api/v1/auth/logout` |
| `/workspace-selector` | Fetch user-accessible workspaces | `GET /api/v1/workspaces` |
| `/workspace-selector` | Create a new tenant workspace | `POST /api/v1/workspaces` |
| `/workspace-selector` | Set active tenant context | `POST /api/v1/workspaces/{workspace_id}/select` |

---

## 2. Core Dashboard & Project Workspaces

| Frontend Interface View | User Interaction Context | Backend API Endpoint Signature |
| :--- | :--- | :--- |
| `/dashboard` | System status and active telemetry card views | `GET /api/v1/dashboard/summary` |
| `/dashboard` | Recent docking/sim run timelines | `GET /api/v1/dashboard/recent-experiments` |
| `/dashboard` | Real-time security/audit trail preview | `GET /api/v1/dashboard/activity` |
| `/dashboard` | Cluster GPU nodes health overview | `GET /api/v1/dashboard/compute-status` |
| `/research-projects` | List active research portfolios | `GET /api/v1/projects` |
| `/research-projects` | Spin up a new target research project | `POST /api/v1/projects` |
| `/research-projects/{id}` | Read individual project metadata | `GET /api/v1/projects/{project_id}` |
| `/research-projects/{id}` | Edit title/disease fields | `PATCH /api/v1/projects/{project_id}` |
| `/research-projects/{id}` | Archive project | `DELETE /api/v1/projects/{project_id}` |
| `/research-projects/{id}` | Project summary statistics tab | `GET /api/v1/projects/{project_id}/overview` |
| `/research-projects/{id}` | Historical timeline timeline tab | `GET /api/v1/projects/{project_id}/timeline` |
| `/experiments` | Fetch run history within project context | `GET /api/v1/projects/{project_id}/experiments` |
| `/experiments` | Spin up a new multi-stage experiment | `POST /api/v1/projects/{project_id}/experiments` |
| `/reports` | Fetch generated scientific report indexes | `GET /api/v1/projects/{project_id}/reports` |
| `/reports` | Compile a new summary study PDF/HTML | `POST /api/v1/projects/{project_id}/reports` |

---

## 3. Deep Scientific Research Modules

### Targets & Molecular Setup
| Frontend Interface View | User Interaction Context | Backend API Endpoint Signature |
| :--- | :--- | :--- |
| `/targets` | View configurations & current binding coordinates | `GET /api/v1/projects/{project_id}/inputs` |
| `/targets` | Save global grid bounds & default receptor | `PUT /api/v1/projects/{project_id}/inputs` |
| `/targets` | Update active file indicators | `PATCH /api/v1/projects/{project_id}/inputs/files` |
| `/targets` | Save custom grid box center-size coordinates | `PATCH /api/v1/projects/{project_id}/inputs/binding-site` |
| `/targets` | Verify all required inputs are configured | `GET /api/v1/projects/{project_id}/inputs/completeness` |
| `/targets` | List available proteins and structures | `GET /api/v1/projects/{project_id}/targets` |
| `/targets` | Import new target files (PDB/PDBQT/UniProt) | `POST /api/v1/projects/{project_id}/targets` |
| `/targets` | Run structural rankers and resolution scoring | `POST /api/v1/projects/{project_id}/targets/rank` |
| `/molecules` | Search and explore active SMILES database | `GET /api/v1/projects/{project_id}/molecules` |
| `/molecules` | Upload SDF ligand libraries or SMILES CSVs | `POST /api/v1/projects/{project_id}/molecules/import` |
| `/molecules` | Trigger generative AI pipeline | `POST /api/v1/projects/{project_id}/molecules/generate` |
| `/molecules` | Apply ADMET/Lipinski properties filters | `POST /api/v1/projects/{project_id}/molecules/filter` |

### Simulation & Compute Workloads
| Frontend Interface View | User Interaction Context | Backend API Endpoint Signature |
| :--- | :--- | :--- |
| `/docking` | Initiate AutoDock Vina computations | `POST /api/v1/projects/{project_id}/docking/runs` |
| `/docking` | List all docking runs (experiments with type=docking) | `GET /api/v1/projects/{project_id}/docking/runs` |
| `/docking` | Get single docking run detail | `GET /api/v1/projects/{project_id}/docking/runs/{experiment_id}` |
| `/docking` | Retrieve binding energy matrix and ranked candidates | `GET /api/v1/projects/{project_id}/docking/results` |
| `/docking` | Resolve pose file metadata + download URL | `GET /api/v1/projects/{project_id}/docking/poses/{pose_id}` |
| `/3d-viewer` | Stream SDF/PDB pose file by file_id | `GET /api/v1/files/{file_id}/download` |
| `/gnina` | Initiate neural CNN structural refinement runs | `POST /api/v1/projects/{project_id}/gnina/runs` |
| `/gnina` | Poll running logs & live execution status | `GET /api/v1/projects/{project_id}/gnina/status` |
| `/gnina` | Download console execution trace | `GET /api/v1/projects/{project_id}/gnina/logs` |
| `/gnina` | Retrieve CNN-score/CNN-affinity output list | `GET /api/v1/projects/{project_id}/gnina/results` |
| `/quantum` | Submit molecular library for quantum mechanics | `POST /api/v1/projects/{project_id}/quantum/runs` |
| `/quantum` | Fetch energy indicators (HOMO, LUMO, bandgap) | `GET /api/v1/projects/{project_id}/quantum/descriptors` |
| `/quantum` | Retrieve QML pre-filter scores | `GET /api/v1/projects/{project_id}/quantum/qml-scores` |
| `/quantum` | Fetch updated priority calculations | `GET /api/v1/projects/{project_id}/quantum/reranking` |
| `/simulations` | Initiate Molecular Dynamics (MD) tracking | `POST /api/v1/projects/{project_id}/simulations/runs` |
| `/simulations` | Read RMSD, RMSF, hydrogen-bond records | `GET /api/v1/projects/{project_id}/simulations/results` |
| `/simulations` | Download trajectory coordinates stream | `GET /api/v1/projects/{project_id}/simulations/trajectories` |
| `/admet` | Initiate safety and clearance screening | `POST /api/v1/projects/{project_id}/admet/runs` |
| `/admet` | Fetch Absorption, Metabolism, Toxicity data | `GET /api/v1/projects/{project_id}/admet/results` |
| `/admet` | Fetch risk alerts and toxicophores matrix | `GET /api/v1/projects/{project_id}/admet/risk-table` |

---

## 4. Visualization & Structural Analysis

| Frontend Interface View | User Interaction Context | Backend API Endpoint Signature |
| :--- | :--- | :--- |
| `/viewer` | List active structures in viewer buffer | `GET /api/v1/projects/{project_id}/viewer/assets` |
| `/viewer` | Stream raw protein PDB/PDBQT coords | `GET /api/v1/projects/{project_id}/viewer/protein/{target_id}` |
| `/viewer` | Stream reference ligand SDF/MOL2 coords | `GET /api/v1/projects/{project_id}/viewer/ligand/{molecule_id}` |
| `/viewer` | Stream active docked pose conformation coords | `GET /api/v1/projects/{project_id}/viewer/pose/{result_id}` |
| `/viewer` | Load interaction fingerprint graphs | `GET /api/v1/projects/{project_id}/viewer/interaction-fingerprint/{result_id}` |
| `/chemical-space` | View t-SNE / UMAP dimensional embeddings | `GET /api/v1/projects/{project_id}/chemical-space` |
| `/chemical-space` | Re-generate chemical space mappings | `POST /api/v1/projects/{project_id}/chemical-space/recompute` |
| `/similarity` | Search molecules using chemical fingerprint similarity | `POST /api/v1/projects/{project_id}/similarity/search` |
| `/similarity` | Retrieve distance and identity matrices | `GET /api/v1/projects/{project_id}/similarity/matrix` |

---

## 5. Copilot & AI Engines

| Frontend Interface View | User Interaction Context | Backend API Endpoint Signature |
| :--- | :--- | :--- |
| `/models` | List active predictive models | `GET /api/v1/models` |
| `/models` | Read parameters of a specific neural network | `GET /api/v1/models/{model_id}` |
| `/models` | Run single-molecule properties prediction playground | `POST /api/v1/models/predict` |
| `/models` | Retrieve ROC-AUC, classification matrices metrics | `GET /api/v1/models/{model_id}/metrics` |
| `/copilot` | Post conversational prompts to AI research assistant | `POST /api/v1/copilot/chat` |
| `/copilot` | List historical copilot conversations | `GET /api/v1/copilot/conversations` |
| `/copilot` | Read entire discussion trail history | `GET /api/v1/copilot/conversations/{conversation_id}` |

---

## 6. Infrastructure & Storage Settings

| Frontend Interface View | User Interaction Context | Backend API Endpoint Signature |
| :--- | :--- | :--- |
| `/compute` | Monitor active GPU compute nodes loading levels | `GET /api/v1/compute/status` |
| `/compute` | List active cluster job IDs and queues | `GET /api/v1/compute/jobs` |
| `/storage` | Inspect total space and directories | `GET /api/v1/storage/summary` |
| `/storage` | Filter active system files registry | `GET /api/v1/storage/files` |
| `/storage` | Direct upload of files to project folder | `POST /api/v1/projects/{project_id}/files/upload` |
| `/storage` | List all files belonging to a project | `GET /api/v1/projects/{project_id}/files` |
| `/storage` | Read metadata details of a specific file | `GET /api/v1/files/{file_id}` |
| `/storage` | Stream file binary bytes for client download | `GET /api/v1/files/{file_id}/download` |
| `/storage` | Safely remove files from system database and store | `DELETE /api/v1/files/{file_id}` |
| `/api-keys` | List active workspace authorization tokens | `GET /api/v1/api-keys` |
| `/api-keys` | Generate new API Token | `POST /api/v1/api-keys` |
| `/api-keys` | Revoke active API Token | `DELETE /api/v1/api-keys/{key_id}` |
| `/integrations` | View third-party tools integration statuses | `GET /api/v1/integrations` |
| `/integrations` | Update API keys or credentials endpoints | `PATCH /api/v1/integrations/{integration_id}` |
| `/integrations` | Verify local q-ai-drug compute node status | `GET /api/v1/integrations/q-ai-drug/health` |

---

## 7. Tenant Workspaces & General Settings

| Frontend Interface View | User Interaction Context | Backend API Endpoint Signature |
| :--- | :--- | :--- |
| `/team` | List active workspace users and invite dates | `GET /api/v1/workspaces/{workspace_id}/members` |
| `/team` | Dispatch new email workspace invitation | `POST /api/v1/workspaces/{workspace_id}/members/invite` |
| `/team` | Modify collaborator access level | `PATCH /api/v1/workspaces/{workspace_id}/members/{member_id}` |
| `/team` | Remove member from workspace team | `DELETE /api/v1/workspaces/{workspace_id}/members/{member_id}` |
| `/billing` | Inspect subscription tiers and credit quotas | `GET /api/v1/billing/summary` |
| `/audit-logs` | Retrieve FDA compliance active logs | `GET /api/v1/audit-logs` |
| `/settings` | Retrieve active user profile data | `GET /api/v1/settings` |
| `/settings` | Update user options or theme preferences | `PATCH /api/v1/settings` |
