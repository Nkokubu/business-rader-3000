import csv
import json
import os
from datetime import datetime
from typing import List, Dict, Optional

EXPORT_DIR = "exports"
FIELDS = ["company_name", "industry", "url", "contact_name", "title", "email"]

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def _coalesce_url(website_hint: Optional[str], domain_hint: Optional[str]) -> Optional[str]:
    url = (website_hint or "").strip()
    if url:
        return url
    dom = (domain_hint or "").strip()
    if dom:
        # prefer full https URL for convenience
        if not dom.startswith("http"):
            return f"https://{dom}"
        return dom
    return None

def build_rows(company_name: str,
               industry: Optional[str],
               website_hint: Optional[str],
               domain_hint: Optional[str],
               contacts: List[Dict[str, Optional[str]]]) -> List[Dict[str, Optional[str]]]:
    """
    Convert your in-memory objects into flat rows for CSV/JSON.
    If contacts is empty, we still return one row with empty contact fields.
    """
    url = _coalesce_url(website_hint, domain_hint)
    base = {
        "company_name": company_name,
        "industry": industry or None,
        "url": url or None,
    }

    if not contacts:
        return [{**base, "contact_name": None, "title": None, "email": None}]

    rows: List[Dict[str, Optional[str]]] = []
    for c in contacts:
        rows.append({
            **base,
            "contact_name": (c.get("name") or None),
            "title": (c.get("title") or None),
            "email": (c.get("email") or None),
        })
    return rows

def export_csv(rows: List[Dict[str, Optional[str]]], basename: str) -> str:
    _ensure_dir(EXPORT_DIR)
    path = os.path.join(EXPORT_DIR, f"{basename}-{_timestamp()}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path

def export_json(rows: List[Dict[str, Optional[str]]], basename: str) -> str:
    _ensure_dir(EXPORT_DIR)
    path = os.path.join(EXPORT_DIR, f"{basename}-{_timestamp()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return path
