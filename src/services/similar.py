import os
import requests
from typing import List, Dict, Optional

WIKIDATA_SEARCH_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

UA = {"User-Agent": "BusinessRadar3000/1.0 (+https://example.com)"}

def _dbg(msg: str):
    if os.getenv("BR_DEBUG") in ("1", "2"):
        print(msg)

# --- Offline-ish fallback (only kicks in if Wikidata is blocked/empty) ---
_AUTOMOTIVE_FALLBACK = [
    {"name": "Toyota Motor Corporation", "website": "https://global.toyota"},
    {"name": "General Motors", "website": "https://www.gm.com"},
    {"name": "Volkswagen Group", "website": "https://www.volkswagen-group.com"},
    {"name": "Hyundai Motor Company", "website": "https://www.hyundai.com"},
    {"name": "Nissan Motor Co., Ltd.", "website": "https://www.nissan-global.com"},
]

def _name_offline_fallback(company_name: str, industry_hint: Optional[str] = None) -> List[Dict[str, str]]:
    low_name = (company_name or "").lower()

    # Basic name-based guess
    is_auto_by_name = any(k in low_name for k in ["motor", "automotive", "auto", "vehicle", "car", "truck", "ev"])

    # Industry-hint based guess (from Day 2 info)
    low_hint = (industry_hint or "").lower()
    is_auto_by_hint = any(k in low_hint for k in ["auto", "automotive", "vehicle"])

    if is_auto_by_name or is_auto_by_hint:
        return [
            {"name": "Toyota Motor Corporation", "website": "https://global.toyota"},
            {"name": "General Motors", "website": "https://www.gm.com"},
            {"name": "Volkswagen Group", "website": "https://www.volkswagen-group.com"},
            {"name": "Hyundai Motor Company", "website": "https://www.hyundai.com"},
            {"name": "Nissan Motor Co., Ltd.", "website": "https://www.nissan-global.com"},
        ]

    # …add other industries here as you like…

    return []

# --- Wikidata helpers ---

def _wikidata_find_qid(company_name: str) -> Optional[str]:
    """Use wbsearchentities to find the company's QID (fuzzy)."""
    try:
        r = requests.get(
            WIKIDATA_SEARCH_URL,
            params={
                "action": "wbsearchentities",
                "search": company_name,
                "language": "en",
                "format": "json",
                "type": "item",
                "limit": 1,
            },
            headers=UA,
            timeout=15,
        )
        r.raise_for_status()
        js = r.json() or {}
        hits = js.get("search") or []
        qid = hits[0]["id"] if hits else None
        _dbg(f"[debug] wikidata qid: {qid}")
        return qid
    except Exception as e:
        _dbg(f"[debug] wikidata search error: {e}")
        return None

def _wikidata_industries_for_qid(qid: str) -> List[str]:
    """Return list of industry QIDs (P452) for the entity QID."""
    q = f"""
    SELECT ?industry WHERE {{
      wd:{qid} wdt:P452 ?industry .
    }}
    """
    try:
        r = requests.get(
            WIKIDATA_SPARQL_URL,
            params={"query": q, "format": "json"},
            headers={**UA, "Accept": "application/sparql-results+json"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json() or {}
        inds = []
        for b in data.get("results", {}).get("bindings", []):
            uri = b["industry"]["value"]  # e.g. https://www.wikidata.org/entity/Q42889
            inds.append(uri.rsplit("/", 1)[-1])
        _dbg(f"[debug] industry qids: {inds}")
        return inds
    except Exception as e:
        _dbg(f"[debug] wikidata industry error: {e}")
        return []

def _wikidata_peers_by_industries(industry_qids: List[str], exclude_qid: str, limit: int = 8) -> List[Dict[str, str]]:
    """Return other companies in any of the given industries that have official websites."""
    if not industry_qids:
        return []
    # Build VALUES clause for multiple industries
    values = " ".join(f"wd:{qid}" for qid in industry_qids)
    q = f"""
    SELECT ?company ?companyLabel ?website WHERE {{
      VALUES ?industry {{ {values} }}
      ?company wdt:P452 ?industry ;
               wdt:P856 ?website .
      FILTER (?company != wd:{exclude_qid})
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    LIMIT {limit}
    """
    try:
        r = requests.get(
            WIKIDATA_SPARQL_URL,
            params={"query": q, "format": "json"},
            headers={**UA, "Accept": "application/sparql-results+json"},
            timeout=25,
        )
        r.raise_for_status()
        data = r.json() or {}
        out: List[Dict[str, str]] = []
        for b in data.get("results", {}).get("bindings", []):
            out.append({
                "name": b["companyLabel"]["value"],
                "website": b.get("website", {}).get("value", ""),
            })
        _dbg(f"[debug] peers returned: {len(out)}")
        return out
    except Exception as e:
        _dbg(f"[debug] wikidata peers error: {e}")
        return []

# --- Public API ---

def get_similar_companies(
    company_name: str,
    industry_hint: Optional[str] = None,   # <-- added
    max_results: int = 8
) -> List[Dict[str, str]]:
    """
    Return a list of {'name': str, 'website': str} for companies similar by industry.
    Order/size may vary by Wikidata coverage. Works without API keys.
    """
    company_name = (company_name or "").strip()
    if not company_name:
        return []

    qid = _wikidata_find_qid(company_name)
    if qid:
        inds = _wikidata_industries_for_qid(qid)
        peers = _wikidata_peers_by_industries(inds, exclude_qid=qid, limit=max_results)
        if peers:
            return peers

    # If Wikidata blocked / empty, offer a helpful offline guess
    return _name_offline_fallback(company_name, industry_hint)

