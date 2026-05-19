"""
Phase 16A — Report Service
Business logic for report creation, section-availability detection,
q-ai-drug import registration, and queue management.

IMPORTANT: No file generation in this phase.
           Only metadata / data-model operations.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from bson import ObjectId

from app.repositories.report_repository import report_repository
from app.repositories.project_repository import project_repository
from app.repositories.workspace_repository import workspace_repository
from app.repositories.target_repository import target_repository
from app.repositories.molecule_repository import molecule_repository
from app.repositories.docking_result_repository import docking_result_repository
from app.repositories.gnina_result_repository import gnina_result_repository
from app.repositories.quantum_result_repository import quantum_result_repository
from app.repositories.admet_result_repository import admet_result_repository
from app.repositories.simulation_result_repository import simulation_result_repository
from app.repositories.file_metadata_repository import file_metadata_repository
from app.core.exceptions import AppException
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-report-service")

# ---------------------------------------------------------------------------
# Section definitions
# ---------------------------------------------------------------------------

SECTION_META = {
    "overview":    "Project Overview",
    "targets":     "Target Summary",
    "candidates":  "Lead Candidates & Molecule Rankings",
    "docking":     "Molecular Docking Results",
    "gnina":       "GNINA CNN Rescoring",
    "quantum":     "Quantum Descriptors",
    "admet":       "ADMET Risk Assessment",
    "simulations": "Molecular Dynamics Simulations",
    "artifacts":   "Imported Artifacts & Files",
}


def _make_section(
    section_id: str,
    status: str,
    summary: str,
    data_refs: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    return {
        "section_id": section_id,
        "title": SECTION_META.get(section_id, section_id.capitalize()),
        "status": status,       # available | missing | pending
        "summary": summary,
        "data_refs": data_refs or {
            "molecules": [],
            "docking_results": [],
            "gnina_results": [],
            "quantum_results": [],
            "admet_results": [],
            "simulation_results": [],
        },
    }


class ReportService:

    # ------------------------------------------------------------------
    # Access control helpers
    # ------------------------------------------------------------------

    async def _get_project_checked(self, project_id: str, user_id: str) -> dict:
        project = await project_repository.get_project_by_id(project_id)
        if not project:
            raise AppException(
                status_code=404,
                code="PROJECT_NOT_FOUND",
                message="Project not found",
            )
        workspace_id = str(project["workspace_id"])
        membership = await workspace_repository.get_membership(workspace_id, user_id)
        if not membership:
            raise AppException(
                status_code=403,
                code="WORKSPACE_ACCESS_DENIED",
                message="User is not an active member of this workspace",
            )
        return project

    # ------------------------------------------------------------------
    # Section availability scanner
    # ------------------------------------------------------------------

    async def _build_section_availability(
        self, project_id: str, sections_requested: List[str]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, bool], Dict[str, int]]:
        """
        Queries each relevant collection to determine section availability.

        Returns:
            sections:   List of section dicts (for report document)
            avail_map:  {section_id: bool} (for summary response)
            counts:     {entity: count}  (for metadata block)
        """
        counts: Dict[str, int] = {}

        # Fire lightweight count queries concurrently-ish (sequential is fine here)
        counts["targets"] = await target_repository.count_by_project(project_id)
        counts["molecules"] = await molecule_repository.count_by_project(project_id)

        # These repositories expose list_results; use limit=1 to get counts cheaply
        _, counts["docking"] = await docking_result_repository.list_results(
            project_id, limit=1
        )
        _, counts["gnina"] = await gnina_result_repository.list_results(
            project_id, limit=1
        )
        _, counts["quantum"] = await quantum_result_repository.list_results(
            project_id, limit=1
        )
        _, counts["admet"] = await admet_result_repository.list_results(
            project_id, limit=1
        )
        _, counts["simulations"] = await simulation_result_repository.list_results(
            project_id, limit=1
        )
        _, counts["files"] = await file_metadata_repository.list_metadata_by_project(
            project_id, limit=1
        )

        avail: Dict[str, bool] = {
            "overview":    True,
            "targets":     counts["targets"] > 0,
            "candidates":  counts["molecules"] > 0,
            "docking":     counts["docking"] > 0,
            "gnina":       counts["gnina"] > 0,
            "quantum":     counts["quantum"] > 0,
            "admet":       counts["admet"] > 0,
            "simulations": counts["simulations"] > 0,
            "artifacts":   counts["files"] > 0,
        }

        sections: List[Dict[str, Any]] = []
        for sec_id in sections_requested:
            if sec_id not in SECTION_META:
                continue  # skip unknown section IDs
            is_avail = avail.get(sec_id, False)
            sections.append(
                _make_section(
                    section_id=sec_id,
                    status="available" if is_avail else "missing",
                    summary=(
                        ""
                        if is_avail
                        else "No backend data available for this section yet."
                    ),
                )
            )

        return sections, avail, counts

    # ------------------------------------------------------------------
    # Create draft report
    # ------------------------------------------------------------------

    async def create_report(
        self,
        project_id: str,
        user_id: str,
        title: str,
        report_type: str,
        experiment_id: Optional[str],
        candidate_molecule_ids: List[str],
        target_ids: List[str],
        experiment_ids: List[str],
        sections_requested: List[str],
    ) -> dict:
        project = await self._get_project_checked(project_id, user_id)
        workspace_id = str(project["workspace_id"])

        if report_type not in (
            "project_summary",
            "candidate_dossier",
            "experiment_report",
            "imported_q_ai_drug",
            "custom",
        ):
            raise AppException(
                status_code=400,
                code="INVALID_REPORT_TYPE",
                message=f"Invalid report_type '{report_type}'.",
            )

        # Validate provided molecule IDs belong to project
        validated_mol_ids: List[str] = []
        for mol_id in candidate_molecule_ids:
            mol = await molecule_repository.get_molecule_by_id(mol_id)
            if mol and str(mol.get("project_id")) == project_id:
                validated_mol_ids.append(mol_id)

        # Validate provided target IDs
        validated_target_ids: List[str] = []
        for t_id in target_ids:
            tgt = await target_repository.get_target_by_id(t_id)
            if tgt and str(tgt.get("project_id")) == project_id:
                validated_target_ids.append(t_id)

        sections, avail, counts = await self._build_section_availability(
            project_id, sections_requested
        )

        now = utc_now()
        report_doc: Dict[str, Any] = {
            "report_id": str(uuid.uuid4()),
            "workspace_id": ObjectId(workspace_id),
            "project_id": ObjectId(project_id),
            "experiment_id": ObjectId(experiment_id) if experiment_id else None,
            "title": title,
            "report_type": report_type,
            "status": "draft",
            "source": "qudrugforge",
            "source_module": "reports",
            "candidate_molecule_ids": validated_mol_ids,
            "target_ids": validated_target_ids,
            "experiment_ids": experiment_ids,
            "sections": sections,
            "file_ids": [],
            "primary_file_id": None,
            "metadata": {
                "candidate_count": counts["molecules"],
                "target_count": counts["targets"],
                "has_docking": avail["docking"],
                "has_gnina": avail["gnina"],
                "has_quantum": avail["quantum"],
                "has_admet": avail["admet"],
                "has_simulations": avail["simulations"],
                "imported_source_dir": None,
            },
            "created_by": ObjectId(user_id),
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "error_message": None,
        }

        saved = await report_repository.create_report(report_doc)
        logger.info(
            f"Created draft report {report_doc['report_id']} for project {project_id}"
        )
        return saved

    # ------------------------------------------------------------------
    # List reports
    # ------------------------------------------------------------------

    async def list_reports(
        self,
        project_id: str,
        user_id: str,
        report_type: Optional[str],
        status: Optional[str],
        skip: int,
        limit: int,
    ) -> Tuple[List[dict], int]:
        await self._get_project_checked(project_id, user_id)
        return await report_repository.list_reports(
            project_id=project_id,
            report_type=report_type,
            status=status,
            skip=skip,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Get single report
    # ------------------------------------------------------------------

    async def get_report(
        self, project_id: str, report_id: str, user_id: str
    ) -> dict:
        await self._get_project_checked(project_id, user_id)
        report = await report_repository.get_by_report_id(report_id)
        if not report or str(report.get("project_id")) != project_id:
            raise AppException(
                status_code=404,
                code="REPORT_NOT_FOUND",
                message="Report not found",
            )
        return report

    # ------------------------------------------------------------------
    # Update report (safe fields only)
    # ------------------------------------------------------------------

    async def update_report(
        self,
        project_id: str,
        report_id: str,
        user_id: str,
        update_data: dict,
    ) -> dict:
        report = await self.get_report(project_id, report_id, user_id)

        safe_fields = {}
        if "title" in update_data and update_data["title"]:
            safe_fields["title"] = update_data["title"]
        if "candidate_molecule_ids" in update_data:
            safe_fields["candidate_molecule_ids"] = update_data["candidate_molecule_ids"]
        if "target_ids" in update_data:
            safe_fields["target_ids"] = update_data["target_ids"]
        if "sections_requested" in update_data:
            # Rebuild sections with new requested list
            sections, _, _ = await self._build_section_availability(
                project_id, update_data["sections_requested"]
            )
            safe_fields["sections"] = sections

        if not safe_fields:
            return report

        safe_fields["updated_at"] = utc_now()
        return await report_repository.update_report(report_id, safe_fields)

    # ------------------------------------------------------------------
    # Delete report
    # ------------------------------------------------------------------

    async def delete_report(
        self,
        project_id: str,
        report_id: str,
        user_id: str,
        delete_files: bool = False,
    ) -> bool:
        report = await self.get_report(project_id, report_id, user_id)

        # Optionally delete linked files (Phase 16B can extend this)
        if delete_files and report.get("file_ids"):
            from app.services.file_service import file_service
            for fid in report["file_ids"]:
                try:
                    await file_service.delete_file(fid, user_id)
                except Exception as exc:
                    logger.warning(f"Could not delete report file {fid}: {exc}")

        return await report_repository.delete_report(report_id)

    # ------------------------------------------------------------------
    # Queue generation (marks draft → queued)
    # ------------------------------------------------------------------

    async def queue_generation(
        self, project_id: str, report_id: str, user_id: str
    ) -> dict:
        report = await self.get_report(project_id, report_id, user_id)

        # Imported q-ai-drug reports should not be re-queued for generation
        if report.get("report_type") == "imported_q_ai_drug":
            raise AppException(
                status_code=400,
                code="INVALID_OPERATION",
                message=(
                    "Imported q-ai-drug reports cannot be regenerated. "
                    "Create a new report of type 'project_summary' or 'candidate_dossier' instead."
                ),
            )

        allowed_statuses = {"draft", "failed"}
        current_status = report.get("status", "draft")
        if current_status not in allowed_statuses:
            raise AppException(
                status_code=400,
                code="INVALID_STATUS_TRANSITION",
                message=(
                    f"Report in status '{current_status}' cannot be queued. "
                    f"Only draft/failed reports may be queued for generation."
                ),
            )

        updated = await report_repository.update_report(
            report_id,
            {"status": "queued", "updated_at": utc_now(), "error_message": None},
        )
        logger.info(f"Queued report {report_id} for generation (project {project_id})")
        return updated

    # ------------------------------------------------------------------
    # Get report files
    # ------------------------------------------------------------------

    async def get_report_files(
        self, project_id: str, report_id: str, user_id: str
    ) -> List[Dict[str, Any]]:
        report = await self.get_report(project_id, report_id, user_id)
        file_ids: List[str] = report.get("file_ids", [])

        # Also include legacy single-file fields for backward compat
        for legacy_key in ("pdf_file_id", "csv_file_id", "sdf_file_id", "html_file_id"):
            fid = report.get(legacy_key)
            if fid and fid not in file_ids:
                file_ids.append(fid)

        results = []
        for fid in file_ids:
            meta = await file_metadata_repository.get_metadata_by_file_id(fid)
            if meta:
                results.append({
                    "file_id": fid,
                    "filename": meta.get("original_filename", fid),
                    "file_type": meta.get("file_type", "generated_report"),
                    "mime_type": meta.get("mime_type", "application/octet-stream"),
                    "size_bytes": meta.get("size_bytes", 0),
                    "download_url": f"/api/v1/files/{fid}/download",
                })
        return results

    # ------------------------------------------------------------------
    # Import q-ai-drug report artifacts
    # ------------------------------------------------------------------

    async def import_q_ai_drug_report(
        self,
        project_id: str,
        user_id: str,
        title: Optional[str],
        source_output_dir: Optional[str],
        explicit_file_ids: List[str],
    ) -> dict:
        project = await self._get_project_checked(project_id, user_id)
        workspace_id = str(project["workspace_id"])

        run_name = None
        # Validate source_output_dir if provided
        if source_output_dir:
            from app.utils.safe_paths import resolve_and_validate_run_dir
            # This resolves and validates the path, raising 404 or 400 if unsafe or missing!
            resolved_dir = resolve_and_validate_run_dir(source_output_dir=source_output_dir)
            run_name = resolved_dir.name

            # Deduplication guard
            existing = await report_repository.find_duplicate_import(
                project_id, source_output_dir
            )
            if existing:
                logger.info(
                    f"Returning existing imported report {existing['report_id']} "
                    f"(source_output_dir={source_output_dir})"
                )
                return existing

        # Resolve file IDs
        if explicit_file_ids:
            # Validate each provided file belongs to this project
            resolved: List[str] = []
            for fid in explicit_file_ids:
                meta = await file_metadata_repository.get_metadata_by_file_id(fid)
                if not meta:
                    raise AppException(
                        status_code=404,
                        code="FILE_NOT_FOUND",
                        message=f"File '{fid}' not found in file registry.",
                    )
                if str(meta.get("project_id")) != project_id:
                    raise AppException(
                        status_code=403,
                        code="FILE_ACCESS_DENIED",
                        message=f"File '{fid}' does not belong to project '{project_id}'.",
                    )
                resolved.append(fid)
            file_ids = resolved
        else:
            # Auto-discover imported report artifacts for this project
            file_ids = await self._discover_q_ai_drug_report_files(project_id, source_output_dir)

        if not file_ids:
            raise AppException(
                status_code=404,
                code="NO_REPORT_FILES_FOUND",
                message=(
                    "No q-ai-drug report artifact files found for this project. "
                    "Run the artifact importer first, or provide explicit file_ids."
                ),
            )

        # Check if at least one PDF or HTML report file exists
        has_report_format = False
        for fid in file_ids:
            meta = await file_metadata_repository.get_metadata_by_file_id(fid)
            if meta:
                name = (meta.get("original_filename") or "").lower()
                if name.endswith((".pdf", ".html", ".htm")):
                    has_report_format = True
                    break
        
        if not has_report_format:
            raise AppException(
                status_code=404,
                code="NO_REPORT_FORMATS_FOUND",
                message=(
                    "No report.pdf or report.html was found among the registered files. "
                    "Please ensure the artifact importer imported report files successfully."
                ),
            )

        # Determine primary file (prefer PDF, fall back to HTML)
        primary_file_id = await self._choose_primary_file(file_ids)

        # Determine report title
        report_title = title
        if not report_title or report_title.strip() == "":
            if run_name:
                report_title = f"Imported q-ai-drug Report ({run_name})"
            else:
                report_title = "Imported q-ai-drug Report"

        now = utc_now()
        report_doc: Dict[str, Any] = {
            "report_id": str(uuid.uuid4()),
            "workspace_id": ObjectId(workspace_id),
            "project_id": ObjectId(project_id),
            "experiment_id": None,
            "title": report_title,
            "report_type": "imported_q_ai_drug",
            "status": "imported",
            "source": "q_ai_drug",
            "source_module": "reports",
            "candidate_molecule_ids": [],
            "target_ids": [],
            "experiment_ids": [],
            "sections": [
                _make_section(
                    "overview",
                    "available",
                    "Report imported from q-ai-drug artifact output.",
                )
            ],
            "file_ids": file_ids,
            "primary_file_id": primary_file_id,
            "metadata": {
                "candidate_count": 0,
                "target_count": 0,
                "has_docking": False,
                "has_gnina": False,
                "has_quantum": False,
                "has_admet": False,
                "has_simulations": False,
                "imported_source_dir": source_output_dir,
            },
            "created_by": ObjectId(user_id),
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "error_message": None,
        }

        saved = await report_repository.create_report(report_doc)
        logger.info(
            f"Registered imported q-ai-drug report {report_doc['report_id']} "
            f"for project {project_id} with {len(file_ids)} file(s)"
        )
        return saved

    async def _discover_q_ai_drug_report_files(self, project_id: str, source_output_dir: Optional[str] = None) -> List[str]:
        """Search the files collection for q-ai-drug report artifacts."""
        # Fetch all files for the project — then filter by type/source/name
        items, _ = await file_metadata_repository.list_metadata_by_project(
            project_id, limit=500
        )

        run_name = None
        if source_output_dir:
            cleaned = source_output_dir.replace("\\", "/").rstrip("/")
            if "/" in cleaned:
                run_name = cleaned.split("/")[-1]
            else:
                run_name = cleaned

        file_ids: List[str] = []
        for meta in items:
            # If run_name is provided, filter out files that don't match the run name
            if run_name:
                file_run_name = meta.get("metadata", {}).get("q_ai_drug_run_name")
                if file_run_name and str(file_run_name).lower() != run_name.lower():
                    continue

            source_module = meta.get("source_module", "")
            file_type = meta.get("file_type", "")
            orig_name: str = (meta.get("original_filename") or "").lower()
            is_report_source = source_module in ("q_ai_drug", "reports", "q_ai_drug_import")
            is_report_type = file_type in (
                "generated_report", "imported_report", "report", "q_ai_drug_artifact"
            )
            is_report_filename = "report" in orig_name and orig_name.endswith(
                (".pdf", ".html", ".htm")
            )
            if is_report_source or is_report_type or is_report_filename:
                file_ids.append(meta["file_id"])
        return file_ids

    async def _choose_primary_file(self, file_ids: List[str]) -> Optional[str]:
        """Return the PDF file_id if present, otherwise the first HTML, else first."""
        pdf_fid: Optional[str] = None
        html_fid: Optional[str] = None
        for fid in file_ids:
            meta = await file_metadata_repository.get_metadata_by_file_id(fid)
            if not meta:
                continue
            name: str = (meta.get("original_filename") or "").lower()
            mime: str = (meta.get("mime_type") or "").lower()
            if name.endswith(".pdf") or "pdf" in mime:
                pdf_fid = fid
                break
            elif name.endswith((".html", ".htm")) or "html" in mime:
                html_fid = fid
        return pdf_fid or html_fid or (file_ids[0] if file_ids else None)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    async def get_project_report_summary(
        self, project_id: str, user_id: str
    ) -> Dict[str, Any]:
        await self._get_project_checked(project_id, user_id)

        status_counts = await report_repository.count_by_status(project_id)
        total = await report_repository.count_total(project_id)

        # Reuse section scanner for availability map (no sections_requested needed)
        _, avail, _ = await self._build_section_availability(
            project_id, list(SECTION_META.keys())
        )

        return {
            "project_id": project_id,
            "total_reports": total,
            "completed_reports": status_counts.get("completed", 0),
            "draft_reports": status_counts.get("draft", 0),
            "imported_reports": status_counts.get("imported", 0),
            "failed_reports": status_counts.get("failed", 0),
            "available_sections": avail,
        }


report_service = ReportService()
