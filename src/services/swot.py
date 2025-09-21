import re
from typing import Dict, List

# Simple keyword patterns → tag (you can tune these anytime)
_PATTERNS = [
    # Positives / Strength-leaning
    (r"\braises?|raised|funding|financing|series [a-z]\b", "funding"),
    (r"\bacquires?|acquired|acquisition|merger|merges with|takeover", "mna"),
    (r"\bpartnership|partners with|collaborat(es|ion)|alliance", "partner"),
    (r"\blaunch(es|ed)?|introduc(es|ed)|rolls out|unveil(s|ed)", "launch"),
    (r"\bexpands?|expansion|opens new|new (office|plant|factory|facility|market)", "expansion"),
    (r"\brecord (revenue|profit|growth)|beats? (expectations|estimates)", "strong_results"),

    # Negatives / Weakness- or Threat-leaning
    (r"\blayoffs?|cuts jobs|job cuts|workforce reduction", "layoffs"),
    (r"\b(loss|decline|misses? estimates|misses? expectations)\b", "weak_results"),
    (r"\blawsuit|sued|litigation|class action", "lawsuit"),
    (r"\bfine(d)?|penalty|sanction", "regulatory"),
    (r"\brecall(s|ed)?|safety issue|defect", "recall"),
    (r"\bdata breach|cyberattack|ransomware|security incident", "security"),
    (r"\bsupply chain disruption|shortage|strike|union action", "supply"),
]

# How tags map to SWOT buckets (primary → list, secondary → optional)
_TAG_TO_SWOT = {
    "funding":       ("Strengths", "Opportunities"),
    "mna":           ("Strengths", "Opportunities"),
    "partner":       ("Strengths", "Opportunities"),
    "launch":        ("Strengths", "Opportunities"),
    "expansion":     ("Opportunities", "Strengths"),
    "strong_results":("Strengths", None),

    "layoffs":       ("Weaknesses", "Threats"),
    "weak_results":  ("Weaknesses", None),
    "lawsuit":       ("Threats", "Weaknesses"),
    "regulatory":    ("Threats", "Weaknesses"),
    "recall":        ("Weaknesses", "Threats"),
    "security":      ("Threats", "Weaknesses"),
    "supply":        ("Threats", "Weaknesses"),
}

def _tag_for_title(title: str) -> str | None:
    t = (title or "").lower()
    for pat, tag in _PATTERNS:
        if re.search(pat, t, flags=re.I):
            return tag
    return None

def generate_swot_from_news(company: str, news: List[Dict], max_items_per_bucket: int = 5) -> Dict[str, List[str]]:
    """
    Input: company name and your scan_news(...) list of dicts:
      {kind, title, summary, url, date}
    Output: dict with keys Strengths/Weaknesses/Opportunities/Threats → list of bullet strings.
    """
    swot = {"Strengths": [], "Weaknesses": [], "Opportunities": [], "Threats": []}
    seen_lines = set()

    for n in news:
        title = (n.get("title") or "")[:240]
        url   = n.get("url") or ""
        date  = n.get("date") or ""
        # Prefer explicit tags from our Day-6 classifier, else regex
        tag = None
        kind = (n.get("kind") or "").lower()
        if "fund" in kind:
            tag = "funding"
        elif "m&a" in kind or "acquisition" in kind:
            tag = "mna"
        elif "expansion" in kind:
            tag = "expansion"
        # fallback to regex on the title
        tag = tag or _tag_for_title(title)
        if not tag:
            continue

        primary, secondary = _TAG_TO_SWOT.get(tag, (None, None))
        if not primary:
            continue

        line = f"{title}" + (f" ({date})" if date else "")
        if url:
            line += f" — {url}"

        # dedupe and cap per bucket
        if line in seen_lines:
            continue
        seen_lines.add(line)

        # primary bucket
        if len(swot[primary]) < max_items_per_bucket:
            swot[primary].append(line)

        # optional secondary bucket (only if still space and not same)
        if secondary and secondary != primary and len(swot[secondary]) < max_items_per_bucket:
            swot[secondary].append(line)

    return swot
