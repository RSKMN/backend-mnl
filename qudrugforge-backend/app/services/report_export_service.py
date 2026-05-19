import csv
import io
from typing import Any, Dict, List, Tuple


CSV_COLUMNS = [
    "compound_id",
    "molecule_id",
    "smiles",
    "status",
    "mw",
    "logp",
    "qed",
    "tpsa",
    "docking_affinity",
    "docking_pose_rank",
    "gnina_cnn_pose_score",
    "gnina_cnn_affinity",
    "gnina_cnn_vs",
    "homo_ev",
    "lumo_ev",
    "gap_ev",
    "dipole_debye",
    "qml_score",
    "quantum_rank",
    "lipinski_violations",
    "ames_toxicity_risk",
    "herg_risk",
    "hepatotoxicity_risk",
    "overall_risk",
    "admet_recommendation",
    "rmsd_avg",
    "rmsf_avg",
    "stability_score",
    "final_recommendation",
]


class ReportExportService:
    def render_csv(self, candidate_rows: List[Dict[str, Any]]) -> bytes:
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in candidate_rows:
            writer.writerow({column: self._stringify(row.get(column)) for column in CSV_COLUMNS})
        return buffer.getvalue().encode("utf-8")

    def render_sdf(self, candidate_rows: List[Dict[str, Any]]) -> Tuple[bytes, str, List[str]]:
        rows_with_smiles = [row for row in candidate_rows if row.get("smiles")]
        warnings: List[str] = []
        if not rows_with_smiles:
            return b"", "skipped", ["SDF export skipped because no candidate SMILES or structures were available."]

        try:
            return self._render_rdkit_sdf(rows_with_smiles)
        except Exception:
            warnings.append("RDKit was unavailable or failed; generated metadata-only SDF fallback.")
            return self._render_metadata_only_sdf(rows_with_smiles), "metadata_only_fallback", warnings

    def _render_rdkit_sdf(self, candidate_rows: List[Dict[str, Any]]) -> Tuple[bytes, str, List[str]]:
        from rdkit import Chem  # type: ignore

        buffer = io.StringIO()
        writer = Chem.SDWriter(buffer)
        skipped = 0
        for row in candidate_rows:
            mol = Chem.MolFromSmiles(str(row.get("smiles")))
            if mol is None:
                skipped += 1
                continue
            mol.SetProp("_Name", str(row.get("compound_id") or row.get("molecule_id") or "candidate"))
            for key, value in row.items():
                if value is not None:
                    mol.SetProp(str(key), self._stringify(value))
            writer.write(mol)
        writer.close()

        warnings = []
        if skipped:
            warnings.append(f"SDF RDKit export skipped {skipped} candidate(s) with invalid SMILES.")
        content = buffer.getvalue()
        if not content.strip():
            return self._render_metadata_only_sdf(candidate_rows), "metadata_only_fallback", [
                "RDKit could not parse any candidate SMILES; generated metadata-only SDF fallback."
            ]
        return content.encode("utf-8"), "rdkit", warnings

    def _render_metadata_only_sdf(self, candidate_rows: List[Dict[str, Any]]) -> bytes:
        records = []
        for row in candidate_rows:
            name = row.get("compound_id") or row.get("molecule_id") or "candidate"
            lines = [
                str(name),
                "  QuDrugForge metadata-only SDF",
                "",
                "  0  0  0  0  0  0            999 V2000",
                "M  END",
            ]
            for key, value in row.items():
                if value is not None:
                    lines.extend([f"> <{key}>", self._stringify(value), ""])
            lines.append("$$$$")
            records.append("\n".join(lines))
        return ("\n".join(records) + "\n").encode("utf-8")

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)


report_export_service = ReportExportService()
