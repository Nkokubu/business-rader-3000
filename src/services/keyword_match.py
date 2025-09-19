import re
import difflib
import urllib.parse
from typing import Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "BusinessRadar3000/1.0 (+https://example.com)"}

# --- Curated synonyms you can expand freely
_SYNONYMS: Dict[str, List[str]] = {
    "ai": ["artificial intelligence", "machine learning", "ml", "deep learning"],
    "saas": ["software as a service", "subscription software", "cloud software"],
    "crm": ["customer relationship management", "sales platform"],
    "procurement": ["purchasing", "sourcing", "supplier management"],
    "ev": ["electric vehicle", "battery electric", "e-mobility"],
    "chip": ["semiconductor", "integrated circuit", "ic", "microchip"],
    "erp": ["enterprise resource planning"],
    "expansion": ["expands", "expansion", "opens new", "new office", "new plant", "new factory", "new facility", "new market"],
}

# --- Public helpers (you can reuse these from main or tests)

def expand_keywords(keywords: List[str]) -> List[str]:
    """Expand with simple synonyms; keep unique, lowercased."""
    out: List[str] = []
    seen = set()
    for k in keywords:
        base = k.strip().lower()
        if not base:
            continue
        for alt in _SYNONYMS.get(base, []) + [base]:
            if alt not in seen:
                seen.add(alt)
                out.append(alt)
    return out

def resolve_domain_from_url_or_domain(url_or_domain: Optional[str]) -> Optional[str]:
    """Accept full URL ('https://acme.com') or bare domain ('acme.com') and return 'acme.com'."""
    if not url_or_domain:
        return None
    s = url_or_domain.strip()
    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    try:
        host = urllib.parse.urlparse(s).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return None

def fetch_text_pages(base_domain: str, extra_paths: Optional[List[str]] = None, max_follow: int = 3) -> List[Tuple[str, str]]:
    """
    Fetch homepage + common pages, lightly follow a few internal links that look relevant.
    Returns list of (url, visible_text).
    """
    base_url = f"https://{base_domain}"
    paths = ["", "/", "/about", "/about-us", "/solutions", "/products", "/platform", "/contact"] + (extra_paths or [])
    urls = [urllib.parse.urljoin(base_url + "/", p) for p in paths]

    pages: List[Tuple[str, str]] = []
    for u in urls:
        html = _get(u)
        if not html:
            continue
        pages.append((u, _visible_text(html)))
        # Follow a few internal links that mention our likely sections
        links = _extract_internal_links(html, base_url, keywords=["solution", "product", "platform", "case", "customers"])
        for lk in links[:max_follow]:
            h2 = _get(lk)
            if h2:
                pages.append((lk, _visible_text(h2)))
    return pages

def match_keywords(text: str, include: List[str], exclude: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """
    Return {matched, excluded} keyword lists using exact, substring, and fuzzy logic.
    """
    include = [k.lower() for k in include if k.strip()]
    exclude = [k.lower() for k in (exclude or []) if k.strip()]

    # Normalize text
    t = _normalize(text)

    # Exact/substring hits
    matched = set(k for k in include if k in t)

    # Fuzzy: catch near-misses (e.g., 'e mobility' ~ 'e-mobility')
    for k in include:
        ratio = difflib.SequenceMatcher(None, k, t).find_longest_match(0, len(k), 0, len(t)).size / max(1, len(k))
        if ratio >= 0.75:
            matched.add(k)

    excluded = set(k for k in exclude if k in t)
    return {"matched": sorted(matched), "excluded": sorted(excluded)}

def score_keyword_relevance(pages: List[Tuple[str, str]], include: List[str], exclude: Optional[List[str]] = None) -> Dict:
    """
    Score relevance across multiple pages. Returns:
    {
      "score": int,
      "evidence": [{"url": ..., "snippet": ..., "keywords": [...]}, ...],
      "matched_keywords": [...],
      "excluded_keywords": [...]
    }
    """
    include = expand_keywords(include)
    exclude = expand_keywords(exclude or [])

    total_score = 0
    evidence = []
    all_matched = set()
    all_excluded = set()

    for url, text in pages:
        res = match_keywords(text, include, exclude)
        if not res["matched"]:
            continue
        # Score: +10 per unique keyword hit on this page (diminishing returns handled by set)
        page_hits = sorted(set(res["matched"]) - all_matched)
        if page_hits:
            total_score += 10 * len(page_hits)
            all_matched.update(page_hits)
            snippet = _make_snippet(text, page_hits[0])
            evidence.append({"url": url, "snippet": snippet, "keywords": page_hits})

        all_excluded.update(res["excluded"])

    # Penalty for excluded keywords
    total_score -= 5 * len(all_excluded)

    return {
        "score": max(total_score, 0),
        "evidence": evidence[:5],
        "matched_keywords": sorted(all_matched),
        "excluded_keywords": sorted(all_excluded),
    }

def flag_business(company_name: str,
                  url_or_domain: Optional[str],
                  include_keywords: List[str],
                  exclude_keywords: Optional[List[str]] = None,
                  threshold: int = 10) -> Dict:
    """
    High-level helper:
      1) Resolve domain,
      2) Fetch a few pages,
      3) Score relevance,
      4) Return flag + details.
    """
    dom = resolve_domain_from_url_or_domain(url_or_domain)
    if not dom:
        return {"flag": False, "score": 0, "matched_keywords": [], "excluded_keywords": [], "evidence": [], "domain": None}

    pages = fetch_text_pages(dom)
    scored = score_keyword_relevance(pages, include_keywords, exclude_keywords)
    return {
        "flag": scored["score"] >= threshold,
        "score": scored["score"],
        "matched_keywords": scored["matched_keywords"],
        "excluded_keywords": scored["excluded_keywords"],
        "evidence": scored["evidence"],
        "domain": dom,
    }

# ---------------- internal utils ----------------

def _get(url: str, timeout: int = 15) -> Optional[str]:
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        r.raise_for_status()
        if "text/html" not in (r.headers.get("Content-Type") or ""):
            return None
        return r.text
    except Exception:
        return None

def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Remove script/style/nav/footer
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.extract()
    text = soup.get_text(" ", strip=True)
    return _normalize(text)

def _normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[\u2010-\u2015]", "-", s)  # normalize dashes
    s = re.sub(r"[^a-z0-9%+@.\- ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _extract_internal_links(html: str, base: str, keywords: Optional[List[str]] = None) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        url = urllib.parse.urljoin(base + "/", href)
        if not url.startswith(base):
            continue
        txt = (a.get_text() or "").lower()
        if keywords and not any(k in (href.lower() + " " + txt) for k in keywords):
            continue
        links.append(url)
    # dedupe
    out, seen = [], set()
    for u in links:
        if u not in seen:
            out.append(u)
            seen.add(u)
    return out

def _make_snippet(text: str, keyword: str, radius: int = 80) -> str:
    """Short context window around the first occurrence of keyword."""
    i = text.find(keyword.lower())
    if i == -1:
        return text[:160] + "..."
    start = max(i - radius, 0)
    end = min(i + len(keyword) + radius, len(text))
    return ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
