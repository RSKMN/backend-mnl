import html
import io
from datetime import datetime
from typing import Any, Dict, List

from app.services.report_export_service import CSV_COLUMNS


DISCLAIMER = (
    "Computational decision-support only. This report is not clinical or medical advice "
    "and does not establish safety, efficacy, or suitability for human use."
)


class ReportRenderService:
    def render_html(self, context: Dict[str, Any]) -> bytes:
        report = context["report"]
        project = context["project"]
        sections = set(context.get("include_sections") or [])
        candidates = context.get("candidate_rows", [])
        targets = context.get("targets", [])
        inputs = context.get("project_inputs") or {}
        files = context.get("files", [])
        generated_at = context["generated_at"].isoformat()

        parts = [
            "<!doctype html><html><head><meta charset=\"utf-8\">",
            f"<title>{self._e(report.get('title', 'QuDrugForge Report'))}</title>",
            "<style>",
            "body{font-family:Arial,Helvetica,sans-serif;color:#17202a;margin:32px;line-height:1.45}",
            "h1{font-size:28px;margin:0 0 8px}h2{font-size:18px;margin-top:28px;border-bottom:1px solid #ccd6dd;padding-bottom:6px}",
            "table{border-collapse:collapse;width:100%;font-size:12px;margin-top:10px}th,td{border:1px solid #d8e0e6;padding:6px;text-align:left;vertical-align:top}",
            "th{background:#eef3f6}.muted{color:#64717d}.pill{display:inline-block;border:1px solid #ccd6dd;padding:2px 6px;margin:2px;border-radius:4px}",
            "</style></head><body>",
            f"<h1>{self._e(report.get('title', 'QuDrugForge Report'))}</h1>",
            f"<p class=\"muted\">Generated {self._e(generated_at)}</p>",
        ]

        if "overview" in sections:
            parts.extend([
                "<h2>Project Overview</h2>",
                f"<p><strong>{self._e(project.get('name', 'Project'))}</strong></p>",
                f"<p>{self._e(project.get('description') or 'No project description provided.')}</p>",
                "<p>",
                f"Disease: {self._e(project.get('disease_type') or inputs.get('disease_type') or 'not specified')}<br>",
                f"Cancer: {self._e(project.get('cancer_type') or 'not specified')}<br>",
                f"Target gene: {self._e(inputs.get('target_gene') or 'not specified')}<br>",
                f"UniProt: {self._e(inputs.get('uniprot_id') or 'not specified')}",
                "</p>",
            ])

        if "targets" in sections:
            parts.append("<h2>Targets</h2>")
            parts.append("<p>" + ", ".join(self._target_label(t) for t in targets[:20]) if targets else "No target records available." + "</p>")

        if "candidates" in sections:
            parts.append("<h2>Candidate Summary</h2>")
            parts.append(self._candidate_table(candidates))
            parts.append("<h2>Top Candidates</h2>")
            parts.append(self._top_candidate_list(candidates[:10]))

        if "docking" in sections:
            parts.append("<h2>Docking</h2>")
            parts.append(self._metric_summary(candidates, "docking_affinity", "Best docking affinity"))

        if "gnina" in sections:
            parts.append("<h2>GNINA</h2>")
            parts.append(self._metric_summary(candidates, "gnina_cnn_affinity", "Best GNINA CNN affinity"))

        if "quantum" in sections:
            parts.append("<h2>Quantum/QML</h2>")
            parts.append(self._metric_summary(candidates, "qml_score", "Best QML score", higher_is_better=True))

        if "admet" in sections:
            parts.append("<h2>ADMET</h2>")
            parts.append(self._risk_table(candidates))

        if "simulations" in sections:
            parts.append("<h2>Simulations/MD</h2>")
            parts.append(self._metric_summary(candidates, "stability_score", "Best stability score", higher_is_better=True))

        if "artifacts" in sections:
            parts.append("<h2>Artifacts and Files</h2>")
            parts.append(self._files_list(files))

        parts.extend([
            "<h2>Wet-Lab Validation Recommendation</h2>",
            self._wet_lab_html(),
            "<h2>Disclaimer</h2>",
            f"<p>{self._e(DISCLAIMER)}</p>",
            "</body></html>",
        ])
        return "".join(parts).encode("utf-8")

    def render_pdf(self, context: Dict[str, Any]) -> bytes:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        story = [
            Paragraph(self._e(context["report"].get("title", "QuDrugForge Report")), styles["Title"]),
            Paragraph(f"Generated {context['generated_at'].isoformat()}", styles["Normal"]),
            Spacer(1, 12),
            Paragraph("Project Summary", styles["Heading2"]),
            Paragraph(self._project_summary_text(context), styles["Normal"]),
            Spacer(1, 8),
            Paragraph("Candidate Ranking", styles["Heading2"]),
        ]

        rows = [["Compound", "SMILES", "Docking", "GNINA", "QML", "ADMET", "Recommendation"]]
        for candidate in context.get("candidate_rows", [])[: context.get("top_n", 50)]:
            rows.append([
                self._s(candidate.get("compound_id")),
                self._s(candidate.get("smiles"))[:32],
                self._s(candidate.get("docking_affinity")),
                self._s(candidate.get("gnina_cnn_affinity")),
                self._s(candidate.get("qml_score")),
                self._s(candidate.get("overall_risk")),
                self._s(candidate.get("final_recommendation")),
            ])
        table = Table(rows, repeatRows=1, colWidths=[70, 145, 55, 55, 55, 60, 95])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f6")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ccd6dd")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.extend([table, Spacer(1, 12)])

        for title, text in [
            ("Section Summaries", self._section_summary_text(context)),
            ("ADMET Risk", self._admet_text(context.get("candidate_rows", []))),
            ("Wet-Lab Validation Recommendation", self._wet_lab_text()),
            ("Artifact References", self._artifact_text(context.get("files", []))),
            ("Disclaimer", DISCLAIMER),
        ]:
            story.extend([Paragraph(title, styles["Heading2"]), Paragraph(self._e(text), styles["Normal"]), Spacer(1, 8)])

        doc.build(story)
        return buffer.getvalue()

    def _candidate_table(self, candidates: List[Dict[str, Any]]) -> str:
        columns = ["compound_id", "smiles", "docking_affinity", "gnina_cnn_affinity", "qml_score", "overall_risk", "final_recommendation"]
        header = "".join(f"<th>{self._e(col)}</th>" for col in columns)
        rows = []
        for candidate in candidates:
            rows.append("<tr>" + "".join(f"<td>{self._e(candidate.get(col))}</td>" for col in columns) + "</tr>")
        return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows) or '<tr><td colspan=\"7\">No candidates available.</td></tr>'}</tbody></table>"

    def _top_candidate_list(self, candidates: List[Dict[str, Any]]) -> str:
        if not candidates:
            return "<p>No ranked candidates available.</p>"
        return "<ol>" + "".join(
            f"<li><strong>{self._e(c.get('compound_id') or c.get('molecule_id'))}</strong>: {self._e(c.get('final_recommendation'))}</li>"
            for c in candidates
        ) + "</ol>"

    def _risk_table(self, candidates: List[Dict[str, Any]]) -> str:
        columns = ["compound_id", "lipinski_violations", "ames_toxicity_risk", "herg_risk", "hepatotoxicity_risk", "overall_risk", "admet_recommendation"]
        header = "".join(f"<th>{self._e(col)}</th>" for col in columns)
        rows = ["<tr>" + "".join(f"<td>{self._e(c.get(col))}</td>" for col in columns) + "</tr>" for c in candidates]
        return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows) or '<tr><td colspan=\"7\">No ADMET records available.</td></tr>'}</tbody></table>"

    def _files_list(self, files: List[Dict[str, Any]]) -> str:
        if not files:
            return "<p>No artifact metadata available.</p>"
        return "<ul>" + "".join(f"<li>{self._e(f.get('original_filename'))} ({self._e(f.get('file_type'))})</li>" for f in files[:100]) + "</ul>"

    def _metric_summary(self, candidates: List[Dict[str, Any]], key: str, label: str, higher_is_better: bool = False) -> str:
        values = [c for c in candidates if isinstance(c.get(key), (int, float))]
        if not values:
            return f"<p>{self._e(label)}: no data available.</p>"
        best = max(values, key=lambda c: c[key]) if higher_is_better else min(values, key=lambda c: c[key])
        return f"<p>{self._e(label)}: {self._e(best.get(key))} for {self._e(best.get('compound_id'))}.</p>"

    def _wet_lab_html(self) -> str:
        return "<ul>" + "".join(f"<li>{self._e(item)}</li>" for item in self._wet_lab_items()) + "</ul>"

    def _wet_lab_text(self) -> str:
        return " ".join(self._wet_lab_items())

    def _wet_lab_items(self) -> List[str]:
        return [
            "Prioritize candidates with low docking or GNINA affinity, strong QML/quantum ranking, and acceptable ADMET risk.",
            "Avoid candidates flagged as high ADMET risk unless a specific counter-screen rationale exists.",
            "Select chemically diverse candidates when clustering or chemical-space annotations are available.",
            "Suggested confirmatory assays: biochemical binding assay, cell viability assay, ADMET/tox counter-screen, hERG follow-up for elevated risk, and MD validation when stability data is missing or weak.",
        ]

    def _project_summary_text(self, context: Dict[str, Any]) -> str:
        project = context["project"]
        return f"{project.get('name', 'Project')}: {project.get('description') or 'No description provided.'}"

    def _section_summary_text(self, context: Dict[str, Any]) -> str:
        counts = context.get("counts", {})
        return (
            f"Targets: {counts.get('targets', 0)}. Molecules: {counts.get('molecules', 0)}. "
            f"Docking: {counts.get('docking', 0)}. GNINA: {counts.get('gnina', 0)}. "
            f"Quantum: {counts.get('quantum', 0)}. ADMET: {counts.get('admet', 0)}. "
            f"Simulations: {counts.get('simulations', 0)}."
        )

    def _admet_text(self, candidates: List[Dict[str, Any]]) -> str:
        risks = [self._s(c.get("overall_risk")) for c in candidates if c.get("overall_risk") is not None]
        return "No ADMET risk records available." if not risks else f"Overall risk values represented in top candidates: {', '.join(sorted(set(risks)))}."

    def _artifact_text(self, files: List[Dict[str, Any]]) -> str:
        if not files:
            return "No file artifacts were linked in the source data."
        return "; ".join(f"{f.get('original_filename')} ({f.get('file_type')})" for f in files[:20])

    def _target_label(self, target: Dict[str, Any]) -> str:
        label = target.get("gene") or target.get("protein_name") or target.get("uniprot_id") or target.get("_id")
        return f"<span class=\"pill\">{self._e(label)}</span>"

    def _e(self, value: Any) -> str:
        return html.escape(self._s(value))

    def _s(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)


report_render_service = ReportRenderService()
