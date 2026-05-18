from __future__ import annotations

from typing import Any, Dict, Optional


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp_stability_score(value: Any) -> Optional[float]:
    numeric = _to_float(value)
    if numeric is None:
        return None
    return max(0.0, min(1.0, numeric))


def compute_stability_score(
    stability_score: Any = None,
    rmsd_avg: Any = None,
    rmsf_avg: Any = None,
) -> Optional[float]:
    provided = clamp_stability_score(stability_score)
    if provided is not None:
        return provided

    components = []
    rmsd_value = _to_float(rmsd_avg)
    if rmsd_value is not None:
        components.append(max(0.0, 1.0 - (rmsd_value / 5.0)))

    rmsf_value = _to_float(rmsf_avg)
    if rmsf_value is not None:
        components.append(max(0.0, 1.0 - (rmsf_value / 3.0)))

    if not components:
        return None

    return sum(components) / len(components)


def classify_stability(stability_score: Any) -> str:
    score = _to_float(stability_score)
    if score is None:
        return "unknown"
    if score >= 0.75:
        return "stable"
    if score >= 0.45:
        return "moderate"
    return "unstable"


def _get_nested_numeric(doc: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        if key in doc:
            value = _to_float(doc.get(key))
            if value is not None:
                return value

    metadata = doc.get("metadata")
    if isinstance(metadata, dict):
        for key in keys:
            if key in metadata:
                value = _to_float(metadata.get(key))
                if value is not None:
                    return value

    raw = doc.get("raw")
    if isinstance(raw, dict):
        for key in keys:
            if key in raw:
                value = _to_float(raw.get(key))
                if value is not None:
                    return value

    return None


def extract_chart_time(doc: Dict[str, Any], fallback_index: int) -> float:
    value = _get_nested_numeric(doc, "time", "frame_time", "frame", "step", "timestamp")
    if value is not None:
        return value
    return float(max(0, fallback_index - 1))


def build_simulation_result_payload(doc: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
    data = dict(doc)
    if data.get("_id") is not None:
        data["id"] = str(data.pop("_id"))
    elif data.get("id") is not None:
        data["id"] = str(data["id"])

    for field in ("project_id", "workspace_id", "experiment_id"):
        if data.get(field) is not None:
            data[field] = str(data[field])

    rmsd_avg = _get_nested_numeric(data, "rmsd_avg", "rmsd")
    rmsf_avg = _get_nested_numeric(data, "rmsf_avg", "rmsf")
    stability_score = compute_stability_score(
        stability_score=data.get("stability_score", data.get("md_stability_score")),
        rmsd_avg=rmsd_avg,
        rmsf_avg=rmsf_avg,
    )

    source_file_id = data.get("source_file_id")
    if source_file_id is not None:
        source_file_id = str(source_file_id)

    return {
        "id": data.get("id"),
        "experiment_id": data.get("experiment_id"),
        "project_id": data.get("project_id"),
        "workspace_id": data.get("workspace_id"),
        "compound_id": data.get("compound_id"),
        "smiles": data.get("smiles"),
        "md_stability_score": clamp_stability_score(data.get("md_stability_score", data.get("stability_score"))),
        "stability_score": stability_score,
        "rmsd": rmsd_avg,
        "rmsd_avg": rmsd_avg,
        "rmsf": rmsf_avg,
        "rmsf_avg": rmsf_avg,
        "stability_class": classify_stability(stability_score),
        "source_file_id": source_file_id,
        "trajectory_file_id": source_file_id,
        "trajectory_download_url": f"{base_url}/api/v1/files/{source_file_id}/download" if source_file_id else None,
        "import_id": data.get("import_id"),
        "status": data.get("status"),
        "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        "raw": data.get("raw") if isinstance(data.get("raw"), dict) else {},
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


def build_simulation_trajectory_payload(doc: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
    data = dict(doc)
    file_id = str(data.get("file_id") or data.get("_id") or "")
    linked_experiment_id = data.get("linked_experiment_id")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

    experiment_id = data.get("experiment_id") or linked_experiment_id or metadata.get("experiment_id")
    molecule_id = data.get("molecule_id") or metadata.get("molecule_id")
    target_id = data.get("target_id") or metadata.get("target_id")

    return {
        "file_id": file_id,
        "experiment_id": str(experiment_id) if experiment_id is not None else None,
        "molecule_id": str(molecule_id) if molecule_id is not None else None,
        "target_id": str(target_id) if target_id is not None else None,
        "original_filename": data.get("original_filename", data.get("stored_filename", "")),
        "file_type": data.get("file_type"),
        "mime_type": data.get("mime_type"),
        "size_bytes": data.get("size_bytes"),
        "download_url": f"{base_url}/api/v1/files/{file_id}/download" if file_id else None,
        "viewer_url": f"{base_url}/3d-viewer/{file_id}" if file_id else None,
        "project_id": str(data.get("project_id", "")),
        "workspace_id": str(data.get("workspace_id", "")),
        "source_module": data.get("source_module"),
        "linked_experiment_id": str(linked_experiment_id) if linked_experiment_id else None,
        "created_at": data.get("created_at"),
    }