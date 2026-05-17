# QuDrugForge™ MongoDB Database Plan

This document details the planned MongoDB database structure, schemas, collection descriptions, and key indices designed for the QuDrugForge™ backend.

---

## 1. Overview of Database Strategy

* **Technology**: MongoDB utilizing `motor` (async driver) and `pymongo` (sync/admin driver).
* **Validation**: FastAPI inputs and DB integrations are mapped through strict Pydantic schemas.
* **Relations**: Handled via document embedding for high-density components (e.g. metadata sub-blocks) and UUID/ObjectID referencing for top-level entities (e.g., workspaces, projects, files).

---

## 2. Collection Schemas & Fields

### A. Identity & Workspaces

#### `users`
Represents platform user accounts.
```json
{
  "_id": "UUID",
  "email": "string (unique)",
  "hashed_password": "string",
  "full_name": "string",
  "is_active": "boolean",
  "is_superuser": "boolean",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
* **Indices**: `email` (Unique)

#### `workspaces`
Top-level environments containing projects and assets.
```json
{
  "_id": "UUID",
  "name": "string",
  "slug": "string (unique)",
  "owner_id": "UUID (ref: users)",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
* **Indices**: `slug` (Unique)

#### `workspace_members`
Association collection mapping users to workspaces.
```json
{
  "_id": "UUID",
  "workspace_id": "UUID (ref: workspaces)",
  "user_id": "UUID (ref: users)",
  "role": "string (admin, researcher, guest)",
  "joined_at": "datetime"
}
```
* **Indices**: `[workspace_id, user_id]` (Compound Unique)

---

### B. Core Research Entities

#### `projects`
Logical containers representing a target program (e.g. EGFR mutation study).
```json
{
  "_id": "UUID",
  "workspace_id": "UUID (ref: workspaces)",
  "name": "string",
  "description": "string",
  "disease_area": "string",
  "created_by": "UUID (ref: users)",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
* **Indices**: `workspace_id`, `[workspace_id, name]`

#### `project_inputs`
Configurations and primary scientific inputs active for a specific research project.
```json
{
  "_id": "UUID",
  "project_id": "UUID (ref: projects)",
  "active_target_id": "UUID (ref: targets, optional)",
  "binding_site": {
    "center_x": "float",
    "center_y": "float",
    "center_z": "float",
    "size_x": "float",
    "size_y": "float",
    "size_z": "float"
  },
  "grid_spacing": "float",
  "exhaustiveness": "integer",
  "updated_at": "datetime"
}
```
* **Indices**: `project_id` (Unique)

#### `files`
Metadata catalog for all uploaded proteins, ligand libraries, and computed file artifacts.
```json
{
  "_id": "UUID",
  "project_id": "UUID (ref: projects)",
  "workspace_id": "UUID (ref: workspaces)",
  "filename": "string",
  "file_type": "string (protein, ligand_library, docking_pose, report, temp)",
  "storage_path": "string (relative to storage root)",
  "checksum": "string (sha256 hash)",
  "size_bytes": "long",
  "uploaded_by": "UUID (ref: users)",
  "created_at": "datetime"
}
```
* **Indices**: `project_id`, `checksum`, `[project_id, file_type]`

#### `targets`
Represent molecular target receptors (proteins/enzymes) under investigation.
```json
{
  "_id": "UUID",
  "project_id": "UUID (ref: projects)",
  "name": "string",
  "uniprot_id": "string",
  "pdb_code": "string",
  "file_id": "UUID (ref: files)",
  "resolution": "float",
  "organism": "string",
  "created_at": "datetime"
}
```
* **Indices**: `project_id`, `uniprot_id`

#### `molecules`
Catalog of active ligands, structural variants, generated drug candidates.
```json
{
  "_id": "UUID",
  "project_id": "UUID (ref: projects)",
  "smiles": "string",
  "chembl_id": "string (optional)",
  "molecular_weight": "float",
  "log_p": "float",
  "hbd": "integer",
  "hba": "integer",
  "tpsa": "float",
  "source": "string (import, generator_v1)",
  "created_at": "datetime"
}
```
* **Indices**: `[project_id, smiles]` (Unique within project)

---

### C. Experiments & Scientific Results

#### `experiments`
Execution records of specific scientific runs.
```json
{
  "_id": "UUID",
  "project_id": "UUID (ref: projects)",
  "name": "string",
  "type": "string (docking, gnina, quantum, simulation, admet)",
  "status": "string (pending, running, completed, failed)",
  "parameters": "document (custom variables per run type)",
  "compute_job_id": "string (external q-ai-drug job key)",
  "started_at": "datetime",
  "completed_at": "datetime",
  "error_message": "string (optional)"
}
```
* **Indices**: `project_id`, `status`, `compute_job_id`

#### `docking_results`
Calculated outputs from AutoDock Vina tasks.
```json
{
  "_id": "UUID",
  "experiment_id": "UUID (ref: experiments)",
  "molecule_id": "UUID (ref: molecules)",
  "target_id": "UUID (ref: targets)",
  "affinity_score": "float",
  "rmsd_lbound": "float",
  "rmsd_ubound": "float",
  "pose_file_id": "UUID (ref: files)",
  "created_at": "datetime"
}
```
* **Indices**: `experiment_id`, `affinity_score`, `molecule_id`

#### `gnina_results`
Enhanced CNN scoring results from deep learning docking runs.
```json
{
  "_id": "UUID",
  "experiment_id": "UUID (ref: experiments)",
  "molecule_id": "UUID (ref: molecules)",
  "target_id": "UUID (ref: targets)",
  "cnn_score": "float",
  "cnn_affinity": "float",
  "pose_file_id": "UUID (ref: files)",
  "created_at": "datetime"
}
```
* **Indices**: `experiment_id`, `cnn_score`

#### `quantum_results`
Computed quantum-mechanical indicators.
```json
{
  "_id": "UUID",
  "experiment_id": "UUID (ref: experiments)",
  "molecule_id": "UUID (ref: molecules)",
  "homo_energy": "float",
  "lumo_energy": "float",
  "bandgap": "float",
  "dipole_moment": "float",
  "polarizability": "float",
  "prefilter_score": "float",
  "kernel_score": "float",
  "created_at": "datetime"
}
```
* **Indices**: `experiment_id`, `prefilter_score`, `kernel_score`

#### `admet_results`
Absorption, Distribution, Metabolism, Excretion, and Toxicity safety profiles.
```json
{
  "_id": "UUID",
  "experiment_id": "UUID (ref: experiments)",
  "molecule_id": "UUID (ref: molecules)",
  "hbb_permeability": "float",
  "caco2_permeability": "float",
  "herg_inhibition": "string (high, low, none)",
  "solubility_score": "float",
  "toxicity_class": "integer",
  "risk_score": "float",
  "created_at": "datetime"
}
```
* **Indices**: `experiment_id`, `risk_score`

#### `simulation_results`
Molecular Dynamics (MD) tracking records.
```json
{
  "_id": "UUID",
  "experiment_id": "UUID (ref: experiments)",
  "target_id": "UUID (ref: targets)",
  "molecule_id": "UUID (ref: molecules)",
  "duration_ns": "float",
  "temperature_k": "float",
  "rmsd_curve": "array of floats",
  "rmsf_curve": "array of floats",
  "trajectory_file_id": "UUID (ref: files)",
  "created_at": "datetime"
}
```
* **Indices**: `experiment_id`

---

### D. Deliverables, Logs, & Helpers

#### `reports`
Comprehensive scientific study summaries generated for workspaces.
```json
{
  "_id": "UUID",
  "project_id": "UUID (ref: projects)",
  "name": "string",
  "file_id": "UUID (ref: files)",
  "created_by": "UUID (ref: users)",
  "created_at": "datetime"
}
```
* **Indices**: `project_id`

#### `audit_logs`
Chronological operations journal for security, compliance, and FDA regulations context.
```json
{
  "_id": "UUID",
  "workspace_id": "UUID (ref: workspaces)",
  "user_id": "UUID (ref: users)",
  "action": "string (create_project, delete_target, start_docking, etc.)",
  "details": "document (context key-value data)",
  "ip_address": "string",
  "timestamp": "datetime"
}
```
* **Indices**: `workspace_id`, `timestamp`

#### `api_keys`
Access keys for automation integrations and terminal client agents.
```json
{
  "_id": "UUID",
  "user_id": "UUID (ref: users)",
  "name": "string",
  "key_hash": "string",
  "scopes": "array of strings",
  "is_active": "boolean",
  "expires_at": "datetime",
  "created_at": "datetime"
}
```
* **Indices**: `key_hash` (Unique)

#### `copilot_conversations`
Persistent AI support histories for molecular discovery guidance.
```json
{
  "_id": "UUID",
  "user_id": "UUID (ref: users)",
  "project_id": "UUID (ref: projects)",
  "title": "string",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
* **Indices**: `user_id`, `project_id`

#### `copilot_messages`
Individual communications within a copilot dialog.
```json
{
  "_id": "UUID",
  "conversation_id": "UUID (ref: copilot_conversations)",
  "sender": "string (user, assistant)",
  "content": "string (markdown allowed)",
  "context_entities": {
    "molecule_ids": "array of UUIDs (optional)",
    "target_ids": "array of UUIDs (optional)",
    "experiment_ids": "array of UUIDs (optional)"
  },
  "created_at": "datetime"
}
```
* **Indices**: `conversation_id`, `created_at`
