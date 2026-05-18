from __future__ import annotations

from collections import Counter
from typing import Any


RISK_SCORE_BY_LEVEL = {
    "low": 0.15,
    "medium": 0.5,
    "moderate": 0.5,
    "high": 0.85,
}

CRITICAL_RISK_FIELDS: dict[str, tuple[str, ...]] = {
    "herg_risk": ("herg_risk", "hERG_risk", "herg", "herg_score", "herg_probability"),
    "ames_toxicity_risk": ("ames_toxicity_risk", "ames_risk", "ames_score", "ames_probability"),
    "hepatotoxicity_risk": (
        "hepatotoxicity_risk",
        "hepatotox_risk",
        "hepatotoxicity_score",
        "hepatotoxicity_probability",
    ),
    "clintox_risk": ("clintox_risk", "clintox_toxicity_probability", "clintox_score"),
    "tox21_risk": ("tox21_risk", "tox21_toxicity_probability", "tox21_score"),
}

RADAR_FIELDS: dict[str, tuple[str, ...]] = {
    "toxicity": (
        "toxicity_risk",
        "toxicity_score",
        "tox21_risk",
        "clintox_risk",
        "hepatotoxicity_risk",
        "ames_toxicity_risk",
        "herg_risk",
        "risk_score",
    ),
    "drug_likeness": (
        "drug_likeness_score",
        "qed",
        "lipinski_score",
        "lipinski_violations",
    ),
    "solubility": ("solubility_score", "solubility_risk", "aqueous_solubility_score"),
    "permeability": ("permeability_score", "permeability_risk", "caco2_permeability_score"),
    "metabolism": ("metabolism_score", "metabolism_risk", "cyp_risk", "cyp3a4_risk"),
}

_DISPLAY_NAMES = {
    "herg_risk": "hERG",
    "ames_toxicity_risk": "Ames toxicity",
    "hepatotoxicity_risk": "Hepatotoxicity",
    "clintox_risk": "Clintox",
    "tox21_risk": "Tox21",
}


def _lookup_value(doc: dict[str, Any], names: tuple[str, ...]) -> Any:
    containers = [doc, doc.get("properties"), doc.get("metadata"), doc.get("raw")]
    for name in names:
        for container in containers:
            if isinstance(container, dict) and name in container:
                value = container.get(name)
                if value is not None:
                    return value
    return None


def _coerce_score(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 0.85 if value else 0.15
    if isinstance(value, (int, float)):
        numeric = float(value)
        if 0.0 <= numeric <= 1.0:
            return numeric
        if 1.0 < numeric <= 100.0:
            return numeric / 100.0
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        if text in {"high", "critical", "severe", "positive", "true", "yes", "fail", "failed"}:
            return 0.85
        if text in {"medium", "moderate", "mid", "warning"}:
            return 0.5
        if text in {"low", "pass", "passed", "false", "no", "negative", "safe"}:
            return 0.15
        try:
            numeric = float(text.rstrip("%"))
        except ValueError:
            return None
        if text.endswith("%") and 0.0 <= numeric <= 100.0:
            return numeric / 100.0
        if 0.0 <= numeric <= 1.0:
            return numeric
        return None
    if isinstance(value, (list, tuple, set)):
        scores = [_coerce_score(item) for item in value]
        scores = [item for item in scores if item is not None]
        return max(scores) if scores else None
    if isinstance(value, dict):
        for key in ("score", "value", "risk_score", "probability", "risk", "level"):
            if key in value:
                return _coerce_score(value.get(key))
        for key in ("label", "risk_level", "severity", "state"):
            if key in value:
                return _coerce_score(value.get(key))
    return None


def _score_to_level(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.7:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


def _level_to_score(level: str) -> float:
    return RISK_SCORE_BY_LEVEL.get(level.lower(), 0.0)


def _display_level(level: str) -> str:
    return level.capitalize()


def _badge_tone(level: str) -> str:
    if level == "high":
        return "error"
    if level in {"medium", "moderate"}:
        return "warning"
    if level == "low":
        return "success"
    return "neutral"


def _candidate_label(doc: dict[str, Any]) -> str:
    for key in ("compound_id", "molecule_id", "smiles", "name", "id"):
        value = doc.get(key)
        if value not in (None, ""):
            return str(value)
    if doc.get("_id") is not None:
        return str(doc["_id"])
    return "unknown"


def _lipinski_violations(doc: dict[str, Any]) -> int:
    value = _lookup_value(
        doc,
        (
            "lipinski_violations",
            "lipinski_violation_count",
            "ro5_violations",
            "lipinski_count",
        ),
    )
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(value, str):
        try:
            return max(int(float(value)), 0)
        except ValueError:
            return 1 if value.strip().lower() in {"fail", "failed", "violation", "violations"} else 0
    try:
        return max(int(float(value)), 0)
    except (TypeError, ValueError):
        return 0


def _radar_metric(doc: dict[str, Any], field: str) -> dict[str, Any]:
    raw_value = _lookup_value(doc, RADAR_FIELDS[field])
    score = _coerce_score(raw_value)

    if field == "drug_likeness" and score is None:
        lipinski_violations = _lipinski_violations(doc)
        score = max(0.0, 1.0 - min(lipinski_violations / 4.0, 1.0))

    return {
        "value": score,
        "label": _display_level(_score_to_level(score)) if score is not None else "Unknown",
    }


def classify_admet_result(doc: dict[str, Any]) -> dict[str, Any]:
    critical_risks: dict[str, dict[str, Any]] = {}
    risk_flags: list[str] = []
    critical_scores: list[float] = []

    for field, names in CRITICAL_RISK_FIELDS.items():
        score = _coerce_score(_lookup_value(doc, names))
        level = _score_to_level(score)
        critical_risks[field] = {
            "score": score,
            "level": level,
            "label": _display_level(level),
        }
        if score is not None:
            critical_scores.append(score)
        display_name = _DISPLAY_NAMES[field]
        if level == "high":
            risk_flags.append(f"{display_name} high risk")
        elif level == "medium":
            risk_flags.append(f"{display_name} moderate risk")

    lipinski_violations = _lipinski_violations(doc)
    if lipinski_violations >= 1:
        risk_flags.append("Lipinski violation")
    if lipinski_violations >= 2:
        risk_flags.append("Multiple Lipinski violations")

    if any(item["level"] == "high" for item in critical_risks.values()):
        overall_risk = "high"
    elif any(item["level"] in {"medium", "high"} for item in critical_risks.values()) or lipinski_violations >= 2:
        overall_risk = "medium"
    else:
        overall_risk = "low"

    recommendation = "advance"
    if overall_risk == "high":
        recommendation = "reject"
    elif overall_risk == "medium" or lipinski_violations > 1:
        recommendation = "review"

    overall_risk_score = _level_to_score(overall_risk)
    toxicity_score = max(critical_scores) if critical_scores else _coerce_score(_lookup_value(doc, RADAR_FIELDS["toxicity"]))

    radar = {
        "toxicity": _radar_metric(doc, "toxicity") if toxicity_score is None else {"value": toxicity_score, "label": _display_level(_score_to_level(toxicity_score))},
        "drug_likeness": _radar_metric(doc, "drug_likeness"),
        "solubility": _radar_metric(doc, "solubility"),
        "permeability": _radar_metric(doc, "permeability"),
        "metabolism": _radar_metric(doc, "metabolism"),
    }

    badges = [
        {
            "key": "overall_risk",
            "label": _display_level(overall_risk),
            "level": overall_risk,
            "tone": _badge_tone(overall_risk),
            "score": overall_risk_score,
        },
        {
            "key": "recommendation",
            "label": _display_level(recommendation),
            "level": recommendation,
            "tone": _badge_tone("low" if recommendation == "advance" else "medium" if recommendation == "review" else "high"),
            "score": None,
        },
    ]

    for field, payload in critical_risks.items():
        if payload["level"] == "unknown":
            continue
        badges.append(
            {
                "key": field,
                "label": f"{_DISPLAY_NAMES[field]} {_display_level(payload['level'])}",
                "level": payload["level"],
                "tone": _badge_tone(payload["level"]),
                "score": payload["score"],
            }
        )

    if lipinski_violations >= 1:
        badges.append(
            {
                "key": "lipinski_violations",
                "label": "Multiple Lipinski violations" if lipinski_violations >= 2 else "Lipinski violation",
                "level": "high" if lipinski_violations >= 2 else "medium",
                "tone": _badge_tone("high" if lipinski_violations >= 2 else "medium"),
                "score": float(lipinski_violations),
            }
        )

    table_row = {
        "candidate": _candidate_label(doc),
        "overall_risk": _display_level(overall_risk),
        "recommendation": _display_level(recommendation),
        "row_class": f"risk-{overall_risk}",
        "risk_flags": risk_flags,
        "badges": badges,
    }

    return {
        "overall_risk": overall_risk,
        "overall_risk_score": overall_risk_score,
        "recommendation": recommendation,
        "risk_flags": risk_flags,
        "lipinski_violations": lipinski_violations,
        "critical_risks": critical_risks,
        "radar": radar,
        "badges": badges,
        "table_row": table_row,
        "ui": {
            "badges": badges,
            "table_row": table_row,
        },
    }


def format_admet_result(doc: dict[str, Any]) -> dict[str, Any]:
    return {**doc, **classify_admet_result(doc)}


def summarize_admet_results(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    risk_counts: Counter[str] = Counter()
    recommendation_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    score_totals: Counter[str] = Counter()
    score_counts: Counter[str] = Counter()
    score_keys = ["overall_risk_score", *CRITICAL_RISK_FIELDS.keys(), *RADAR_FIELDS.keys()]

    for item in items:
        classified = classify_admet_result(item)
        overall_risk = classified["overall_risk"]
        recommendation = classified["recommendation"]
        risk_counts[overall_risk] += 1
        recommendation_counts[recommendation] += 1

        score_entries = {"overall_risk_score": classified["overall_risk_score"]}
        for field, payload in classified["critical_risks"].items():
            score_entries[field] = payload["score"]
        for field, payload in classified["radar"].items():
            score_entries[field] = payload["value"]

        for key, value in score_entries.items():
            if value is None:
                continue
            score_totals[key] += float(value)
            score_counts[key] += 1

        for warning in classified["risk_flags"]:
            warning_counts[warning] += 1

    average_scores = {
        key: (score_totals[key] / score_counts[key]) if score_counts[key] else None
        for key in score_keys
    }

    top_warnings = [
        {"label": label, "count": count}
        for label, count in warning_counts.most_common(5)
    ]

    low = risk_counts.get("low", 0)
    medium = risk_counts.get("medium", 0)
    high = risk_counts.get("high", 0)

    return {
        "total": total if total is not None else len(items),
        "total_molecules": total if total is not None else len(items),
        "low": low,
        "medium": medium,
        "moderate": medium,
        "high": high,
        "unknown": risk_counts.get("unknown", 0),
        "risk_counts": {
            "low": low,
            "medium": medium,
            "high": high,
            "unknown": risk_counts.get("unknown", 0),
        },
        "recommendation_counts": {
            "advance": recommendation_counts.get("advance", 0),
            "review": recommendation_counts.get("review", 0),
            "reject": recommendation_counts.get("reject", 0),
        },
        "average_scores": average_scores,
        "top_warnings": top_warnings,
    }