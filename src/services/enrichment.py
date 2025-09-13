import os
import re
import requests
import yfinance as yf
from typing import Optional, Dict, List, Tuple

# ---------------- Debug helpers ----------------

def _dbg(msg: str, level: int = 1):
    # BR_DEBUG unset/0 = silent; 1 = basic; 2 = verbose (HTTP errors)
    try:
        dbg = int(os.getenv("BR_DEBUG", "0"))
    except ValueError:
        dbg = 0
    if dbg >= level:
        print(msg)

UA = {"User-Agent": "BusinessRadar3000/1.0 (+https://example.com)"}

# ---------------- Keyword maps ----------------

_SECTOR_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("Technology", ["software", "semiconductor", "electronics", "it services", "internet", "cloud", "ai", "saas"]),
    ("Consumer Discretionary", [
        "automotive", "auto", "auto manufacturer", "automobile", "motor", "vehicle", "car", "truck", "ev",
        "apparel", "retail", "ecommerce", "online retail", "leisure", "hotel", "restaurant"
    ]),
    ("Communication Services", ["telecom", "media", "entertainment", "broadcast", "social media", "streaming"]),
    ("Financials", ["bank", "insurance", "asset management", "brokerage", "fintech", "financial", "credit", "capital"]),
    ("Health Care", ["pharma", "pharmaceutical", "biotechnology", "biotech", "medical", "health care", "medical devices"]),
    ("Industrials", ["industrial", "machinery", "aerospace", "defense", "logistics", "transportation", "construction", "engineering"]),
    ("Energy", ["oil", "gas", "energy", "renewable", "solar", "wind", "utilities energy"]),
    ("Materials", ["chemical", "chemicals", "mining", "steel", "materials", "commodity", "paper", "forest products"]),
    ("Utilities", ["utility", "utilities", "electric", "water", "power"]),
    ("Real Estate", ["real estate", "reit", "property"]),
    ("Consumer Staples", ["food", "beverage", "household products", "staples", "grocery", "tobacco"]),
]

_NAME_RULES: List[Tuple[re.Pattern, Dict[str, str]]] = [
    # Automotive
    (re.compile(r"\b(ford|toyota|honda|nissan|hyundai|kia|tesla|volkswagen|audi|porsche|bmw|mercedes|gm|general motors|stellantis)\b", re.I),
     {"industry": "Automotive", "sector": "Consumer Discretionary"}),
    (re.compile(r"\b(motor|motors|automotive|auto( |\-)?(mfg|maker|manufacturer)?)\b", re.I),
     {"industry": "Automotive", "sector": "Consumer Discretionary"}),

    # Finance
    (re.compile(r"\b(bank|financial|finance|capital|holdings|insurance|assurance|brokerage)\b", re.I),
     {"industry": "Financial Services", "sector": "Financials"}),

    # Technology
    (re.compile(r"\b(software|semiconductor|micro(electronics)?|systems|technolog(y|ies)|labs|networks|ai|cloud)\b", re.I),
     {"industry": "Software & Services", "sector": "Technology"}),

    # Health Care
    (re.compile(r"\b(pharma(ceutical)?|biotech(nology)?|medical|health(care)?|therapeutics|medicines?|devices?)\b", re.I),
     {"industry": "Health Care", "sector": "Health Care"}),

    # Industrials
    (re.compile(r"\b(aerospace|defense|machinery|industrial|logistics|transport(ation)?)\b", re.I),
     {"industry": "Industrials", "sector": "Industrials"}),

    # Materials / Chemicals
    (re.compile(r"\b(chemical(s)?|materials?|mining|steel)\b", re.I),
     {"industry": "Materials", "sector": "Materials"}),

    # Energy
    (re.compile(r"\b(oil|gas|petroleum|energy|renewable|solar|wind)\b", re.I),
     {"industry": "Energy", "sector": "Energy"}),

    # Consumer Staples
    (re.compile(r"\b(food|beverage|grocery|tobacco)\b", re.I),
     {"industry": "Consumer Staples", "sector": "Consumer Staples"}),

    # Real Estate
    (re.compile(r"\b(reit|real estate|property)\b", re.I),
     {"industry": "Real Estate", "sector": "Real Estate"}),
]

def _normalize(s: Optional[str]) -> Optional[str]:
    return s.strip() if isinstance(s, str) and s.strip() else None

def _guess_sector_from_industry(industry: Optional[str]) -> Optional[str]:
    if not industry:
        return None
    low = industry.lower()
    for sector, keys in _SECTOR_KEYWORDS:
        if any(k in low for k in keys):
            return sector
    return None

# ---------------- Provider 1: Yahoo Finance ----------------

YF_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
YF_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"

def _yf_symbol_search(company_name: str) -> Optional[str]:
    try:
        r = requests.get(
            YF_SEARCH_URL,
            params={"q": company_name, "quotesCount": 5, "newsCount": 0, "lang": "en-US", "region": "US"},
            timeout=15,
            headers=UA,
        )
        r.raise_for_status()
        data = r.json()
        quotes = (data or {}).get("quotes") or []
        if not quotes:
            return None

        name_tokens = {t.lower() for t in company_name.split() if len(t) > 2}
        def score(q):
            qt = q.get("quoteType", "")
            longname = (q.get("longname") or q.get("shortname") or q.get("name") or "").lower()
            hits = sum(1 for t in name_tokens if t in longname)
            return (qt != "EQUITY", -hits, -(q.get("score") or 0))

        quotes.sort(key=score)
        sym = quotes[0].get("symbol")
        return _normalize(sym)
    except Exception as e:
        _dbg(f"[debug] Yahoo symbol search error: {e}", level=2)
        return None

def _yf_quote_summary(symbol: str) -> Optional[Dict[str, Optional[str]]]:
    try:
        r = requests.get(
            YF_QUOTE_SUMMARY_URL.format(symbol=symbol),
            params={"modules": "assetProfile"},
            timeout=15,
            headers=UA,
        )
        r.raise_for_status()
        js = r.json() or {}
        result = (((js.get("quoteSummary") or {}).get("result") or []) or [None])[0] or {}
        ap = result.get("assetProfile") or {}
        industry = _normalize(ap.get("industry"))
        sector = _normalize(ap.get("sector"))
        if industry or sector:
            return {"industry": industry, "sector": sector or _guess_sector_from_industry(industry)}
        return None
    except Exception as e:
        _dbg(f"[debug] Yahoo quoteSummary error: {e}", level=2)
        return None

def _from_yfinance(company_name: str) -> Optional[Dict[str, Optional[str]]]:
    sym = _yf_symbol_search(company_name)
    if not sym:
        return None
    _dbg(f"[debug] Yahoo matched symbol: {sym}", level=2)

    # First try yfinance's info (may be empty sometimes)
    try:
        info = yf.Ticker(sym).get_info()
        industry = _normalize(info.get("industry"))
        sector = _normalize(info.get("sector"))
        if industry or sector:
            return {"industry": industry, "sector": sector or _guess_sector_from_industry(industry)}
    except Exception as e:
        _dbg(f"[debug] yfinance.get_info error: {e}", level=2)

    # Fallback to direct quoteSummary
    return _yf_quote_summary(sym)

# ---------------- Provider 2: Wikidata (SPARQL) ----------------

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

def _from_wikidata(company_name: str) -> Optional[Dict[str, Optional[str]]]:
    queries = [
        f'''
        SELECT ?industryLabel WHERE {{
          ?org rdfs:label "{company_name}"@en ;
               wdt:P452 ?industry .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }} LIMIT 1
        ''',
        f'''
        SELECT ?industryLabel WHERE {{
          ?org wdt:P452 ?industry ;
               rdfs:label ?label .
          FILTER (lang(?label) = "en" && CONTAINS(LCASE(?label), LCASE("{company_name}")))
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }} LIMIT 1
        ''',
    ]

    for q in queries:
        try:
            r = requests.get(
                WIKIDATA_SPARQL_URL,
                params={"query": q},
                headers={**UA, "Accept": "application/sparql-results+json"},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json() or {}
            bindings = ((data.get("results") or {}).get("bindings") or [])
            if not bindings:
                continue
            industry = _normalize(bindings[0]["industryLabel"]["value"])
            if industry:
                return {"industry": industry, "sector": _guess_sector_from_industry(industry)}
        except Exception as e:
            _dbg(f"[debug] Wikidata SPARQL error: {e}", level=2)
            continue
    return None

# ---------------- Provider 3: Google Knowledge Graph ----------------

GOOGLE_KG_URL = "https://kgsearch.googleapis.com/v1/entities:search"

def _from_google_kg(company_name: str) -> Optional[Dict[str, Optional[str]]]:
    api_key = os.getenv("GOOGLE_KG_API_KEY")
    if not api_key:
        return None
    try:
        r = requests.get(
            GOOGLE_KG_URL,
            params={
                "query": company_name,
                "key": api_key,
                "limit": 1,
                "languages": "en",
                "types": "Corporation,Organization",
            },
            headers=UA,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json() or {}
        items = data.get("itemListElement") or []
        if not items:
            return None
        res = (items[0] or {}).get("result") or {}
        desc = _normalize(res.get("description")) or _normalize(res.get("name"))
        industry = desc
        sector = _guess_sector_from_industry(industry)
        if industry or sector:
            return {"industry": industry, "sector": sector}
        return None
    except Exception as e:
        _dbg(f"[debug] Google KG error: {e}", level=2)
        return None

# ---------------- Provider 4: Name-based rules (offline-ish) ----------------

def _from_name_rules(company_name: str) -> Optional[Dict[str, Optional[str]]]:
    name = company_name.strip()
    for pat, out in _NAME_RULES:
        if pat.search(name):
            return {"industry": out["industry"], "sector": out["sector"]}
    return None

# ---------------- Orchestrator ----------------

def get_industry_info(company_name: str) -> Dict[str, Optional[str]]:
    if not company_name or not company_name.strip():
        return {"industry": None, "sector": None}

    providers = (_from_yfinance, _from_wikidata, _from_google_kg, _from_name_rules)

    for provider in providers:
        result = provider(company_name)
        _dbg(f"[debug] provider returned: {provider.__name__} -> {result}", level=1)
        if result and (result.get("industry") or result.get("sector")):
            return {
                "industry": _normalize(result.get("industry")),
                "sector": _normalize(result.get("sector")),
            }

    return {"industry": None, "sector": None}
