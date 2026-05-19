import logging
import uuid
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import AppException
from app.repositories.admet_result_repository import admet_result_repository
from app.repositories.docking_result_repository import docking_result_repository
from app.repositories.experiment_repository import experiment_repository
from app.repositories.file_metadata_repository import file_metadata_repository
from app.repositories.gnina_result_repository import gnina_result_repository
from app.repositories.molecule_repository import molecule_repository
from app.repositories.project_input_repository import project_input_repository
from app.repositories.quantum_result_repository import quantum_result_repository
from app.repositories.report_repository import report_repository
from app.repositories.simulation_result_repository import simulation_result_repository
from app.repositories.target_repository import target_repository
from app.services.report_export_service import report_export_service
from app.services.report_render_service import report_render_service
from app.storage.service import storage_service
from app.utils.datetime import utc_now

logger = logging.getLogger("qudrugforge-report-generation")

SUPPORTED_FORMATS = {"csv", "sdf", "html", "pdf"}
MIME_TYPES = {
    "csv": "text/csv",
    "sdf": "chemical/x-mdl-sdfile",
    "html": "text/html",
    "pdf": "application/pdf",
}
FILENAMES = {
    "csv": "candidate_summary.csv",
    "sdf": "candidates.sdf",
    "html": "report.html",
    "pdf": "report.pdf",
}


class ReportGenerationService:
    async def generate_report(
        self,
        project_id: str,
        report_id: str,
        user_id: str,
        formats: List[str],
        include_sections: List[str],
        top_n: int,
    ) -> Dict[str, Any]:
        from app.services.report_service import report_service

        report = await report_service.get_report(project_id, report_id, user_id)
        if report.get("report_type") == "imported_q_ai_drug":
            raise AppException(
                status_code=400,
                code="INVALID_OPERATION",
                message="Imported q-ai-drug reports cannot be regenerated.",
            )

        requested_formats = self._normalize_formats(formats)
        if not requested_formats:
            raise AppException(status_code=400, code="INVALID_FORMATS", message="At least one supported format is required.")

        await report_repository.update_report(
            report_id,
            {"status": "generating", "updated_at": utc_now(), "error_message": None},
        )

        warnings: List[str] = []
        generated_files: List[Dict[str, Any]] = []
        try:
            context = await self._collect_context(project_id, report, include_sections, top_n)
            candidate_rows = context["candidate_rows"]

            payloads: List[Tuple[str, bytes, Dict[str, Any]]] = []
            if "csv" in requested_formats:
                payloads.append(("csv", report_export_service.render_csv(candidate_rows), {}))
            if "sdf" in requested_formats:
                sdf_bytes, method, sdf_warnings = report_export_service.render_sdf(candidate_rows)
                warnings.extend(sdf_warnings)
                if sdf_bytes:
                    payloads.append(("sdf", sdf_bytes, {"sdf_generation_method": method}))
            if "html" in requested_formats:
                payloads.append(("html", report_render_service.render_html(context), {}))
            if "pdf" in requested_formats:
                try:
                    payloads.append(("pdf", report_render_service.render_pdf(context), {}))
                except ImportError as exc:
                    warnings.append(f"PDF export skipped because reportlab is unavailable: {exc}")

            if not payloads:
                raise AppException(
                    status_code=500,
                    code="REPORT_GENERATION_FAILED",
                    message="No report files were generated.",
                )

            existing_file_ids = list(report.get("file_ids", []))
            new_file_ids: List[str] = []
            format_to_file_id: Dict[str, str] = {}
            for fmt, content, metadata_extra in payloads:
                file_doc = await self._store_generated_file(
                    project_id=project_id,
                    workspace_id=str(report["workspace_id"]),
                    report=report,
                    user_id=user_id,
                    fmt=fmt,
                    content=content,
                    metadata_extra=metadata_extra,
                )
                file_id = file_doc["file_id"]
                new_file_ids.append(file_id)
                format_to_file_id[fmt] = file_id
                generated_files.append({
                    "file_id": file_id,
                    "format": fmt,
                    "filename": file_doc["original_filename"],
                    "download_url": f"/api/v1/files/{file_id}/download",
                })

            primary_file_id = self._choose_primary(format_to_file_id, report.get("primary_file_id"))
            metadata = dict(report.get("metadata") or {})
            metadata.update({
                "last_generated_at": utc_now(),
                "last_generated_formats": list(format_to_file_id.keys()),
                "warnings": warnings,
            })
            if "sdf" in requested_formats and "sdf" in format_to_file_id:
                metadata["sdf_generation_method"] = next(
                    (extra.get("sdf_generation_method") for fmt, _, extra in payloads if fmt == "sdf"),
                    None,
                )

            updated_report = await report_repository.update_report(
                report_id,
                {
                    "status": "completed",
                    "file_ids": existing_file_ids + new_file_ids,
                    "primary_file_id": primary_file_id,
                    "metadata": metadata,
                    "sections": context.get("sections", report.get("sections", [])),
                    "completed_at": utc_now(),
                    "updated_at": utc_now(),
                    "error_message": None,
                },
            )

            return {
                "success": True,
                "report": updated_report,
                "generated_files": generated_files,
                "warnings": warnings,
            }
        except AppException as exc:
            await self._mark_failed(report_id, exc.message)
            raise exc
        except Exception as exc:
            logger.exception("Report generation failed for %s", report_id)
            await self._mark_failed(report_id, str(exc))
            raise AppException(
                status_code=500,
                code="REPORT_GENERATION_FAILED",
                message=f"Report generation failed: {exc}",
            )

    async def create_and_generate_project_summary(
        self,
        project_id: str,
        user_id: str,
        title: str,
        formats: List[str],
        top_n: int,
    ) -> Dict[str, Any]:
        from app.services.report_service import report_service

        report = await report_service.create_report(
            project_id=project_id,
            user_id=user_id,
            title=title,
            report_type="project_summary",
            experiment_id=None,
            candidate_molecule_ids=[],
            target_ids=[],
            experiment_ids=[],
            sections_requested=["overview", "targets", "candidates", "docking", "gnina", "quantum", "admet", "simulations", "artifacts"],
        )
        return await self.generate_report(project_id, report["report_id"], user_id, formats, report["sections"], top_n)

    async def create_and_generate_candidate_dossier(
        self,
        project_id: str,
        user_id: str,
        title: str,
        candidate_molecule_ids: List[str],
        formats: List[str],
        top_n: int,
    ) -> Dict[str, Any]:
        from app.services.report_service import report_service

        report = await report_service.create_report(
            project_id=project_id,
            user_id=user_id,
            title=title,
            report_type="candidate_dossier",
            experiment_id=None,
            candidate_molecule_ids=candidate_molecule_ids,
            target_ids=[],
            experiment_ids=[],
            sections_requested=["overview", "targets", "candidates", "docking", "gnina", "quantum", "admet", "simulations", "artifacts"],
        )
        return await self.generate_report(project_id, report["report_id"], user_id, formats, report["sections"], top_n)

    async def _collect_context(
        self,
        project_id: str,
        report: Dict[str, Any],
        include_sections: List[str],
        top_n: int,
    ) -> Dict[str, Any]:
        from app.services.report_service import report_service
        from app.repositories.project_repository import project_repository

        project = await project_repository.get_project_by_id(project_id)
        project_inputs = await project_input_repository.get_by_project_id(project_id)
        targets, target_count = await target_repository.list_targets(project_id, limit=500)
        molecules, molecule_count = await molecule_repository.list_molecules(project_id, limit=5000)
        docking, docking_count = await docking_result_repository.list_results(project_id, limit=5000)
        gnina, gnina_count = await gnina_result_repository.list_results(project_id, limit=5000)
        quantum, quantum_count = await quantum_result_repository.list_results(project_id, limit=5000)
        admet, admet_count = await admet_result_repository.list_results(project_id, limit=5000)
        simulations, simulations_count = await simulation_result_repository.list_results(project_id, limit=5000)
        experiments, experiments_count = await experiment_repository.list_experiments(project_id, limit=500)
        files, files_count = await file_metadata_repository.list_metadata_by_project(project_id, limit=500)

        requested_ids = set(report.get("candidate_molecule_ids") or [])
        if requested_ids:
            molecules = [m for m in molecules if str(m.get("_id")) in requested_ids]

        sections_requested = [
            section if isinstance(section, str) else section.get("section_id")
            for section in include_sections
        ]
        sections, _, _ = await report_service._build_section_availability(project_id, [s for s in sections_requested if s])
        candidate_rows = self._build_candidate_rows(molecules, docking, gnina, quantum, admet, simulations)
        candidate_rows.sort(key=self._ranking_key)
        candidate_rows = candidate_rows[:top_n]

        return {
            "project": project or {},
            "project_inputs": project_inputs or {},
            "report": report,
            "targets": targets,
            "molecules": molecules,
            "candidate_rows": candidate_rows,
            "docking": docking,
            "gnina": gnina,
            "quantum": quantum,
            "admet": admet,
            "simulations": simulations,
            "experiments": experiments,
            "files": files,
            "sections": sections,
            "include_sections": [s for s in sections_requested if s],
            "top_n": top_n,
            "generated_at": utc_now(),
            "counts": {
                "targets": target_count,
                "molecules": molecule_count,
                "docking": docking_count,
                "gnina": gnina_count,
                "quantum": quantum_count,
                "admet": admet_count,
                "simulations": simulations_count,
                "experiments": experiments_count,
                "files": files_count,
            },
        }

    def _build_candidate_rows(
        self,
        molecules: List[Dict[str, Any]],
        docking: List[Dict[str, Any]],
        gnina: List[Dict[str, Any]],
        quantum: List[Dict[str, Any]],
        admet: List[Dict[str, Any]],
        simulations: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        best_docking = self._best_by_candidate(docking, ["binding_affinity_kcal_mol", "binding_affinity", "affinity"], lower=True)
        best_gnina = self._best_by_candidate(gnina, ["cnn_affinity"], lower=True)
        best_quantum = self._best_by_candidate(quantum, ["quantum_rank", "rank"], lower=True, fallback_fields=["qml_score"], fallback_lower=False)
        best_admet = self._best_by_candidate(admet, ["overall_risk", "risk_score", "toxicity_risk", "risk_level"], lower=True)
        best_sim = self._best_by_candidate(simulations, ["md_stability_score", "stability_score"], lower=False)

        rows: List[Dict[str, Any]] = []
        for molecule in molecules:
            key_candidates = self._candidate_keys(molecule)
            dock = self._lookup(best_docking, key_candidates)
            gni = self._lookup(best_gnina, key_candidates)
            qua = self._lookup(best_quantum, key_candidates)
            adm = self._lookup(best_admet, key_candidates)
            sim = self._lookup(best_sim, key_candidates)
            row = {
                "compound_id": molecule.get("compound_id"),
                "molecule_id": str(molecule.get("_id")),
                "smiles": molecule.get("smiles"),
                "status": molecule.get("status"),
                "final_rank": self._first(molecule, ["final_rank", "rank"]),
                "rank_score": self._first(molecule, ["rank_score", "final_score"]),
                "mw": self._first(molecule, ["mw", "molecular_weight"]),
                "logp": self._first(molecule, ["logp", "LogP"]),
                "qed": molecule.get("qed"),
                "tpsa": molecule.get("tpsa"),
                "docking_affinity": self._first(dock, ["binding_affinity_kcal_mol", "binding_affinity", "affinity", "score"]),
                "docking_pose_rank": self._first(dock, ["pose_rank", "rank"]),
                "gnina_cnn_pose_score": self._first(gni, ["cnn_pose_score", "cnn_score"]),
                "gnina_cnn_affinity": self._first(gni, ["cnn_affinity"]),
                "gnina_cnn_vs": self._first(gni, ["cnn_vs", "cnn_vs_score"]),
                "homo_ev": self._first(qua, ["homo_ev", "homo"]),
                "lumo_ev": self._first(qua, ["lumo_ev", "lumo"]),
                "gap_ev": self._first(qua, ["gap_ev", "homo_lumo_gap_ev", "gap"]),
                "dipole_debye": self._first(qua, ["dipole_debye", "dipole"]),
                "qml_score": self._first(qua, ["qml_score", "quantum_kernel_score", "quantum_prefilter_score"]),
                "quantum_rank": self._first(qua, ["quantum_rank", "rank"]),
                "lipinski_violations": self._first(adm, ["lipinski_violations"]),
                "ames_toxicity_risk": self._first(adm, ["ames_toxicity_risk", "ames_risk"]),
                "herg_risk": self._first(adm, ["herg_risk", "hERG_risk"]),
                "hepatotoxicity_risk": self._first(adm, ["hepatotoxicity_risk"]),
                "overall_risk": self._first(adm, ["overall_risk", "risk_level", "toxicity_risk", "risk_score"]),
                "admet_recommendation": self._first(adm, ["recommendation", "admet_recommendation"]),
                "rmsd_avg": self._first(sim, ["rmsd_avg", "avg_rmsd"]),
                "rmsf_avg": self._first(sim, ["rmsf_avg", "avg_rmsf"]),
                "stability_score": self._first(sim, ["stability_score", "md_stability_score"]),
            }
            row["final_recommendation"] = self._recommend(row)
            rows.append(row)
        return rows

    def _best_by_candidate(
        self,
        docs: List[Dict[str, Any]],
        fields: List[str],
        lower: bool,
        fallback_fields: Optional[List[str]] = None,
        fallback_lower: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        best: Dict[str, Dict[str, Any]] = {}
        for doc in docs:
            value = self._numeric_or_risk(self._first(doc, fields))
            direction = lower
            if value is None and fallback_fields:
                value = self._numeric_or_risk(self._first(doc, fallback_fields))
                direction = fallback_lower
            score = value if value is not None else float("inf")
            if not direction and value is not None:
                score = -value
            for key in self._candidate_keys(doc):
                old = best.get(key)
                old_score = self._doc_sort_score(old, fields, lower, fallback_fields, fallback_lower) if old else float("inf")
                if score < old_score:
                    best[key] = doc
        return best

    async def _store_generated_file(
        self,
        project_id: str,
        workspace_id: str,
        report: Dict[str, Any],
        user_id: str,
        fmt: str,
        content: bytes,
        metadata_extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        file_id = str(uuid.uuid4())
        filename = FILENAMES[fmt]
        stored_filename = f"{file_id}_{filename}"
        destination_path = f"reports/{workspace_id}/{project_id}/{report['report_id']}/{stored_filename}"
        upload = UploadFile(filename=filename, file=BytesIO(content))
        upload.headers = {"content-type": MIME_TYPES[fmt]}
        save_result = await storage_service.get_provider().save_file(upload, destination_path)

        now = utc_now()
        doc = {
            "file_id": file_id,
            "project_id": ObjectId(project_id),
            "workspace_id": ObjectId(workspace_id),
            "uploaded_by": ObjectId(user_id),
            "generated_by": ObjectId(user_id),
            "original_filename": filename,
            "stored_filename": stored_filename,
            "file_type": "generated_report",
            "mime_type": MIME_TYPES[fmt],
            "local_path": save_result["local_path"],
            "size_bytes": save_result["size_bytes"],
            "checksum": save_result["checksum"],
            "source_module": "reports",
            "kind": "generated",
            "artifact_type": fmt,
            "linked_experiment_id": report.get("experiment_id"),
            "storage_provider": settings.STORAGE_PROVIDER,
            "metadata": {
                "report_id": report["report_id"],
                "report_type": report.get("report_type"),
                "format": fmt,
                **metadata_extra,
            },
            "created_at": now,
            "updated_at": now,
        }
        return await file_metadata_repository.create_metadata(doc)

    def _normalize_formats(self, formats: List[str]) -> List[str]:
        normalized = []
        for fmt in formats or []:
            lower = str(fmt).lower().strip()
            if lower in SUPPORTED_FORMATS and lower not in normalized:
                normalized.append(lower)
        return normalized

    def _choose_primary(self, format_to_file_id: Dict[str, str], existing_primary: Optional[str]) -> str:
        return format_to_file_id.get("pdf") or format_to_file_id.get("html") or format_to_file_id.get("csv") or existing_primary

    async def _mark_failed(self, report_id: str, message: str) -> None:
        await report_repository.update_report(
            report_id,
            {"status": "failed", "error_message": message, "updated_at": utc_now()},
        )

    def _lookup(self, mapping: Dict[str, Dict[str, Any]], keys: List[str]) -> Dict[str, Any]:
        for key in keys:
            if key in mapping:
                return mapping[key]
        return {}

    def _candidate_keys(self, doc: Dict[str, Any]) -> List[str]:
        keys = []
        for field in ("molecule_id", "_id", "compound_id", "smiles"):
            value = doc.get(field)
            if value is not None:
                keys.append(str(value))
        return keys

    def _first(self, doc: Optional[Dict[str, Any]], fields: List[str]) -> Any:
        if not doc:
            return None
        for field in fields:
            if field in doc and doc[field] is not None:
                return doc[field]
            metadata = doc.get("metadata") or {}
            if field in metadata and metadata[field] is not None:
                return metadata[field]
            descriptors = doc.get("qm_descriptors") or {}
            if field in descriptors and descriptors[field] is not None:
                return descriptors[field]
        return None

    def _ranking_key(self, row: Dict[str, Any]) -> Tuple[float, float, float, float, float, float, float]:
        final_rank = self._numeric_or_risk(row.get("rank_score") or row.get("final_rank"))
        quantum_rank = self._numeric_or_risk(row.get("quantum_rank"))
        qml_score = self._numeric_or_risk(row.get("qml_score"))
        gnina_affinity = self._numeric_or_risk(row.get("gnina_cnn_affinity"))
        docking_affinity = self._numeric_or_risk(row.get("docking_affinity"))
        overall_risk = self._numeric_or_risk(row.get("overall_risk"))
        qed = self._numeric_or_risk(row.get("qed"))
        return (
            final_rank if final_rank is not None else float("inf"),
            quantum_rank if quantum_rank is not None else float("inf"),
            -qml_score if qml_score is not None else float("inf"),
            gnina_affinity if gnina_affinity is not None else float("inf"),
            docking_affinity if docking_affinity is not None else float("inf"),
            overall_risk if overall_risk is not None else float("inf"),
            -qed if qed is not None else float("inf"),
        )

    def _doc_sort_score(
        self,
        doc: Optional[Dict[str, Any]],
        fields: List[str],
        lower: bool,
        fallback_fields: Optional[List[str]],
        fallback_lower: bool,
    ) -> float:
        if not doc:
            return float("inf")
        value = self._numeric_or_risk(self._first(doc, fields))
        direction = lower
        if value is None and fallback_fields:
            value = self._numeric_or_risk(self._first(doc, fallback_fields))
            direction = fallback_lower
        if value is None:
            return float("inf")
        return value if direction else -value

    def _numeric_or_risk(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().lower()
        risk_map = {"none": 0, "very_low": 0, "low": 1, "medium": 2, "moderate": 2, "high": 3, "very_high": 4}
        if text in risk_map:
            return float(risk_map[text])
        try:
            return float(text)
        except Exception:
            return None

    def _recommend(self, row: Dict[str, Any]) -> str:
        risk = self._numeric_or_risk(row.get("overall_risk"))
        docking = self._numeric_or_risk(row.get("docking_affinity"))
        gnina = self._numeric_or_risk(row.get("gnina_cnn_affinity"))
        qml = self._numeric_or_risk(row.get("qml_score"))
        if risk is not None and risk >= 3:
            return "Deprioritize until ADMET/tox follow-up is reviewed"
        if (gnina is not None and gnina <= -7) or (docking is not None and docking <= -7):
            if qml is None or qml >= 0:
                return "Prioritize for confirmatory screening"
        if qml is not None and qml > 0:
            return "Consider for follow-up if ADMET remains acceptable"
        return "Review with available assay and risk context"


report_generation_service = ReportGenerationService()
