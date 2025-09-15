import os
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "BusinessRadar3000/1.0 (+https://example.com)"}
HUNTER_BASE = "https://api.hunter.io/v2/domain-search"

def _dbg(msg: str):
    if os.getenv("BR_DEBUG") in ("1", "2"):
        print(msg)

# ---------- DOMAIN RESOLUTION (reuse your existing signals) ----------
# We’ll try: 1) enrichment via Yahoo Finance (website) if you pass it in,
#            2) Wikidata P856 (via a tiny helper here),
#            3) last-resort: try to guess from company name (rarely reliable)

WIKIDATA_SEARCH_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

def _wikidata_qid(company_name: str) -> Optional[str]:
    try:
        r = requests.get(
            WIKIDATA_SEARCH_URL,
            params={"action": "wbsearchentities", "search": company_name, "language": "en", "format": "json", "type": "item", "limit": 1},
            headers=UA, timeout=15
        )
        r.raise_for_status()
        hits = (r.json() or {}).get("search") or []
        return hits[0]["id"] if hits else None
    except Exception as e:
        _dbg(f"[debug] wikidata qid error: {e}")
        return None

def _wikidata_website_for_qid(qid: str) -> Optional[str]:
    try:
        r = requests.get(WIKIDATA_ENTITY_URL.format(qid=qid), headers=UA, timeout=15)
        r.raise_for_status()
        js = r.json() or {}
        ent = (js.get("entities") or {}).get(qid) or {}
        claims = ent.get("claims") or {}
        p856 = claims.get("P856") or []  # official website
        for c in p856:
            v = (c.get("mainsnak") or {}).get("datavalue") or {}
            url = (v.get("value") or "").strip()
            if url:
                return url
        return None
    except Exception as e:
        _dbg(f"[debug] wikidata website error: {e}")
        return None

def resolve_company_domain(company_name: str, website_hint: Optional[str] = None) -> Optional[str]:
    """
    Returns 'example.com' (no scheme/path) or None.
    Priority: hint -> Wikidata -> None
    """
    # 1) If a hint exists (e.g., from Yahoo 'website' field), use it
    if website_hint:
        dom = _domain_from_url(website_hint)
        if dom:
            return dom

    # 2) Try Wikidata official website
    qid = _wikidata_qid(company_name)
    if qid:
        site = _wikidata_website_for_qid(qid)
        dom = _domain_from_url(site) if site else None
        if dom:
            return dom

    return None

def _domain_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or "").lower().strip()
        # strip common www
        host = host[4:] if host.startswith("www.") else host
        return host or None
    except Exception:
        return None

# ---------- HUNTER.IO (preferred when key present) ----------
def hunter_domain_search(domain: str, limit: int = 10) -> List[Dict[str, Optional[str]]]:
    """
    Returns [{name, title, email, source}] using Hunter domain search.
    """
    key = os.getenv("HUNTERIO_API_KEY")
    if not key:
        return []
    try:
        r = requests.get(
            HUNTER_BASE,
            params={"domain": domain, "api_key": key, "limit": limit},
            headers=UA, timeout=20
        )
        r.raise_for_status()
        js = r.json() or {}
        data = (js.get("data") or {})
        emails = data.get("emails") or []
        out: List[Dict[str, Optional[str]]] = []
        for e in emails:
            out.append({
                "name": (e.get("first_name") or "") + (" " + e.get("last_name") if e.get("last_name") else ""),
                "title": e.get("position"),
                "email": e.get("value"),
                "source": "hunter",
            })
        return out[:limit]
    except Exception as e:
        _dbg(f"[debug] hunter error: {e}")
        return []

# ---------- LIGHT WEBSITE SCRAPE (fallback; polite & shallow) ----------
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)

def _fetch(url: str, timeout: int = 15) -> Optional[str]:
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "")
        if "text/html" not in ct and "text/plain" not in ct:
            return None
        return r.text
    except Exception as e:
        _dbg(f"[debug] fetch error {url}: {e}")
        return None

def _candidate_paths() -> List[str]:
    # common contact/about pages
    return ["", "/", "/contact", "/contact-us", "/about", "/about-us", "/team", "/imprint", "/legal"]

def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out

def scrape_site_for_emails(domain: str, limit: int = 10) -> List[Dict[str, Optional[str]]]:
    """
    Very shallow crawl: homepage + a few likely pages. Respects basic etiquette (no hammering).
    Returns [{name, title, email, source}] – name/title unknown from generic pages -> None.
    """
    if not domain:
        return []

    base = "https://" + domain
    pages = [base + p for p in _candidate_paths()]
    found: List[str] = []
    for url in pages:
        html = _fetch(url)
        if not html:
            continue
        # 1) direct email regex on page
        found.extend(EMAIL_RE.findall(html))
        if len(found) >= limit:
            break

        # 2) try to follow a couple of same-site links that obviously look like contact pages
        if len(found) < limit:
            links = _extract_internal_contact_links(html, base)
            for lk in links[:3]:  # keep it tiny
                h2 = _fetch(lk)
                if h2:
                    found.extend(EMAIL_RE.findall(h2))
                if len(found) >= limit:
                    break

        time.sleep(0.5)  # be polite

    emails = _dedupe_keep_order(found)[:limit]
    return [{"name": None, "title": None, "email": e, "source": "scrape"} for e in emails]

def _extract_internal_contact_links(html: str, base: str) -> List[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        links: List[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = (a.get_text() or "").lower()
            if href.startswith("mailto:"):
                continue
            # Keep obvious internal contact-ish links
            if any(k in (href.lower() + " " + text) for k in ["contact", "about", "impressum", "imprint", "legal", "team"]):
                url = urllib.parse.urljoin(base + "/", href)
                if urllib.parse.urlparse(url).netloc.endswith(urllib.parse.urlparse(base).netloc):
                    links.append(url)
        return _dedupe_keep_order(links)
    except Exception:
        return []

# ---------- PUBLIC API ----------
def find_emails_for_company(company_name: str, website_hint: Optional[str] = None, limit: int = 10) -> List[Dict[str, Optional[str]]]:
    """
    Resolve domain -> try Hunter -> fallback to shallow site scrape.
    Returns list of {name, title, email, source}
    """
    company_name = (company_name or "").strip()
    if not company_name:
        return []

    domain = resolve_company_domain(company_name, website_hint=website_hint)
    _dbg(f"[debug] resolved domain: {domain}")
    if not domain:
        return []

    # 1) Hunter (if key)
    emails = hunter_domain_search(domain, limit=limit)
    if emails:
        return emails

    # 2) Light scrape
    return scrape_site_for_emails(domain, limit=limit)
