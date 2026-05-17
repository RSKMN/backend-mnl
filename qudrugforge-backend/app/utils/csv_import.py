import csv
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("qudrugforge-csv-import")

def parse_numeric(val: Any) -> Optional[float]:
    """
    Helper to parse values to float, returning None on failure.
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("none", "null", "nan", "na", "-"):
        return None
    try:
        # Check if it can be an integer first
        if "." not in s and "e" not in s.lower():
            return int(s)
        return float(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None

def parse_csv_to_dicts(file_path: Path) -> List[Dict[str, Any]]:
    """
    Parses a CSV or TSV file into a list of dictionaries.
    Strips whitespace from both keys and values.
    """
    if not file_path.exists():
        logger.warning(f"File not found for parsing: {file_path}")
        return []

    # Detect delimiter based on extension
    ext = file_path.suffix.lower()
    delimiter = "\t" if ext in (".tsv", ".txt") else ","

    rows = []
    try:
        # Use utf-8-sig to automatically handle UTF-8 BOM
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            
            # Clean headers: strip whitespace and ignore None/empty headers
            headers = [h.strip() if h else "" for h in reader.fieldnames or []]
            
            for row in reader:
                cleaned_row = {}
                for k, v in row.items():
                    if k is not None:
                        key = k.strip()
                        val = v.strip() if v is not None else ""
                        cleaned_row[key] = val
                rows.append(cleaned_row)
    except Exception as e:
        logger.error(f"Error parsing file {file_path}: {str(e)}")
        # Return empty list on failure rather than crashing entirely
    return rows
