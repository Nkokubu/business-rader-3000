import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

UA = {"User-Agent": "BusinessRadar3000/1.0 (+https://example.com)"}
GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"

# -------- helpers

def _parse_date(d: Optional[str]) -> Optional[str]:
    """
    Try to normalize a date string to 'YYYY-MM-DD'.
    Accept RFC822 (RSS), ISO8601, or simple 'Mon, DD YYYY' formats.
    """
    if not d:
        return None
    d = d.strip()
    # RSS example: 'Wed, 28 Aug 2024 13:02:00 GMT'
    fmts = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%d %b %Y",
        "%b %d, %Y",
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(d, f)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            continue
    # last resort: just return original
    return d

_amount = re.compile(r"\$ ?(\d+(?:\.\d+)?)(?:\s?(k|m|b|bn))?", re.I)
_series = re.compile(r"\bseries\s+([A-Z]{1,2})\b", re.I)
_acquire = re.compile(r"\b(acquires?|acquired|to acquire|merger|merges with|takeover)\b", re.I)
_expand = re.compile(r"\b(expands?|expansion|opens?|launches?|new\s+(office|plant|factory|facility|market))\b", re.I)
_raise  = re.compile(r"\b(raises?|raised|raise|funding|venture round|financing)\b", re.I)

def _kind_from_text(text: str) -> str:
    t = text.lower()
    if _acquire.search(t):
        return "M&A"
    if _raise.search(t):
        return "Funding"
    if _expand.search(t):
        return "Expansion"
    return "Other"

def _money_from_text(text: str) -> Optional[str]:
    m = _amount.search(text)
    if not m:
        return None
    val, suf = m.groups()
    if not suf:
        return f"${val}"
    suf = suf.lower()
    if suf == "k":
        return f"${val}K"
    if suf in ("m",):
        return f"${val}M"
    if suf in ("b", "bn"):
        return f"${val}B"
    return f"${val}{suf.upper()}"

def _series_from_text(text: str) -> Optional[str]:
    s = _series.search(text)
    return f"Series {s.group(1).upper()}" if s else None

def _summarize(company: str, title: str, pub_date: Optional[str], url: str) -> Dict[str, str]:
    """
    Build a short, human-friendly summary line using headline hints.
    """
    kind = _kind_from_text(title)
    money = _money_from_text(title)
    series = _series_from_text(title)
    date_part = f" on {pub_date}" if pub_date else ""
    if kind == "Funding":
        bits = [company, "raised"]
        if money:
            bits.append(money)
        if series:
            bits.append(series)
        line = " ".join(bits).strip() + f"{date_part}."
    elif kind == "M&A":
        line = f"{company} announced M&A activity{date_part}."
    elif kind == "Expansion":
        line = f"{company} announced an expansion{date_part}."
    else:
        line = f"{company} related news{date_part}."
    return {"kind": kind, "title": title, "summary": line, "url": url, "date": pub_date or ""}

# -------- Provider A: Google Programmable Search (CSE)

def _google_cse(company: str, days: int, max_results: int) -> List[Dict[str, str]]:
    key = os.getenv("GOOGLE_API_KEY")
    cx  = os.getenv("GOOGLE_CSE_ID")
    if not key or not cx:
        return []

    # Prefer official press wires / investor pages
    # You can customize these sites in your CSE for better signal quality.
    q_terms = [
        f'"{company}" (acquire OR acquired OR acquisition OR merger OR "to acquire")',
        f'"{company}" (raise OR raised OR raises OR funding OR financing OR "Series A" OR "Series B" OR "Series C")',
        f'"{company}" (expansion OR expands OR opens OR "new office" OR "new plant" OR "new factory" OR "new facility" OR "new market")',
    ]
    results: List[Dict[str, str]] = []
    tbs = None  # CSE doesn’t officially support date filters like normal search; we’ll filter client-side.

    for q in q_terms:
        try:
            resp = requests.get(
                GOOGLE_CSE_URL,
                params={
                    "key": key,
                    "cx": cx,
                    "q": q,
                    "num": min(max_results, 10),
                },
                headers=UA,
                timeout=20,
            )
            resp.raise_for_status()
            js = resp.json() or {}
            items = js.get("items") or []
            for it in items:
                title = it.get("title") or ""
                link  = it.get("link") or ""
                # Try to extract a date from "pagemap" or snippet-ish fields if present
                pagemap = it.get("pagemap") or {}
                metatags = (pagemap.get("metatags") or [{}])[0]
                pub = metatags.get("article:published_time") or metatags.get("og:updated_time") or ""
                pub_norm = _parse_date(pub)
                results.append(_summarize(company, title, pub_norm, link))
        except Exception:
            continue

    # Deduplicate by URL and trim; also client-side filter by date window if present
    seen = set()
    out: List[Dict[str, str]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for r in results:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        if r["date"]:
            try:
                dt = datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except Exception:
                pass
        out.append(r)
        if len(out) >= max_results:
            break
    return out

# -------- Provider B: Google News RSS (no key required)

def _google_rss(company: str, days: int, max_results: int) -> List[Dict[str, str]]:
    # Build a news search for our intents
    # Example RSS: https://news.google.com/rss/search?q=Ford+Motor+Company+funding+OR+acquisition+OR+expands&hl=en-US&gl=US&ceid=US:en
    query = f'{company} (funding OR raises OR raised OR "Series A" OR "Series B" OR "Series C" OR acquisition OR acquires OR acquired OR merger OR expands OR expansion OR "new office" OR "new plant" OR "new factory" OR "new facility" OR "new market")'
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        xml = r.text
    except Exception:
        return []

    # Very light RSS parsing (no extra dependencies)
    items: List[Dict[str, str]] = []
    # Split on <item>…</item>
    for raw in xml.split("<item>")[1:]:
        block = raw.split("</item>")[0]
        def _tag(tag: str) -> str:
            pre = f"<{tag}>"
            post = f"</{tag}>"
            if pre in block and post in block:
                val = block.split(pre, 1)[1].split(post, 1)[0]
                return re.sub(r"<.*?>", "", val).strip()
            return ""
        title = _tag("title")
        link  = _tag("link")
        pub   = _tag("pubDate")
        pub_norm = _parse_date(pub)
        if not title or not link:
            continue
        items.append(_summarize(company, title, pub_norm, link))

    # Date filter & dedupe
    seen = set()
    out: List[Dict[str, str]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        if it["date"]:
            try:
                dt = datetime.strptime(it["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except Exception:
                pass
        out.append(it)
        if len(out) >= max_results:
            break
    return out

# -------- Public API

def scan_news(company: str, days: int = 180, max_results: int = 8) -> List[Dict[str, str]]:
    """
    Returns a list of {kind, title, summary, url, date}.
    Tries Google CSE if keys exist; otherwise falls back to Google News RSS (no key).
    """
    company = (company or "").strip()
    if not company:
        return []

    hits = _google_cse(company, days=days, max_results=max_results)
    if not hits:
        hits = _google_rss(company, days=days, max_results=max_results)
    return hits
