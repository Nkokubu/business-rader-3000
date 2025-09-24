import argparse
import os
from rich import print
from dotenv import load_dotenv

from .services.enrichment import get_industry_info
from .services.similar import get_similar_companies
from .services.contacts import (
    find_emails_for_company,
    filter_contacts_by_title,
    resolve_company_domain,
)
from .services.exporter import build_rows, export_csv, export_json
from .services.news import scan_news
from .services.keyword_match import flag_business, expand_keywords, match_keywords
from .services.swot import generate_swot_from_news
from .services.market_graph import build_and_render_market_map



def cmd_industry(args):
    info = get_industry_info(args.company)
    if info.get("sector") == "Consumer Cyclical":
        info["sector"] = "Consumer Discretionary"
    print(info)


def cmd_similar(args):
    info = get_industry_info(args.company)
    sims = get_similar_companies(args.company, industry_hint=info.get("industry"))
    for s in sims:
        name = (s.get("name") or "").strip()
        url = (s.get("website") or "").strip().rstrip("/")
        if name:
            print(f"- {name}" + (f" ({url})" if url else ""))


def cmd_emails(args):
    website_hint = None
    emails = find_emails_for_company(args.company, website_hint=website_hint, limit=args.limit)
    if args.priority:
        emails = filter_contacts_by_title(emails, top_n=args.limit, min_score=1)
    for e in emails:
        addr = (e.get("email") or "").strip()
        name = (e.get("name") or "").strip()
        title = (e.get("title") or "").strip()
        src = (e.get("source") or "").strip()
        line = f"- {addr}"
        if name:
            line += f" | {name}"
        if title:
            line += f" — {title}"
        if "score" in e:
            line += f"  [score {e['score']}]"
        if src:
            line += f"  [{src}]"
        print(line)


def cmd_news(args):
    news = scan_news(args.company, days=args.days, max_results=args.max)
    if not news:
        print("- (none)")
        return
    for n in news:
        line = f"- [{n['kind']}] {n['summary']}"
        if n.get("date"):
            line += f" ({n['date']})"
        line += f"  {n['url']}"
        print(line)


def cmd_keyword(args):
    # Scan news first for keyword hits (optional but helpful)
    news = scan_news(args.company, days=args.days, max_results=args.max)
    expanded = expand_keywords(args.keywords)
    news_text = " ".join(n.get("title", "") for n in news)
    hits = match_keywords(news_text, expanded)
    if hits["matched"]:
        print("[bold]Keyword match in NEWS:[/bold]", hits["matched"])

    # Website scan
    website_hint = None
    domain = resolve_company_domain(args.company, website_hint=website_hint)
    flagged = flag_business(args.company, url_or_domain=(domain or website_hint), include_keywords=args.keywords)
    print({"flag": flagged["flag"], "score": flagged["score"], "matched": flagged["matched_keywords"]})
    for ev in flagged.get("evidence", []):
        print(f"- {ev['url']} — {ev['snippet']}")


def cmd_swot(args):
    news = scan_news(args.company, days=args.days, max_results=args.max)
    swot = generate_swot_from_news(args.company, news, max_items_per_bucket=args.top)
    for bucket in ("Strengths", "Weaknesses", "Opportunities", "Threats"):
        print(f"[bold]{bucket}[/bold]")
        if not swot[bucket]:
            print("  • (none)")
        else:
            for item in swot[bucket]:
                print(f"  • {item}")


def cmd_export(args):
    info = get_industry_info(args.company)
    website_hint = None  # plug in info.get("website") if you add it
    domain_hint = resolve_company_domain(args.company, website_hint=website_hint)
    emails = find_emails_for_company(args.company, website_hint=website_hint, limit=args.limit)
    if args.priority:
        emails = filter_contacts_by_title(emails, top_n=args.limit, min_score=1)

    rows = build_rows(
        company_name=args.company,
        industry=info.get("industry"),
        website_hint=website_hint,
        domain_hint=domain_hint,
        contacts=emails,
    )
    base = args.company.lower().replace(" ", "_")
    csv_path = export_csv(rows, basename=base)
    json_path = export_json(rows, basename=base)
    print("[bold]Saved files:[/bold]")
    print(f"- CSV : {csv_path}")
    print(f"- JSON: {json_path}")


def cmd_marketmap(args):
    paths = build_and_render_market_map(
        seed_company=args.company,
        get_similar=lambda name: get_similar_companies(name, industry_hint=None),
        max_depth=args.depth,
        max_per_company=args.max_per_node,
        html_out=f"exports/{args.company.lower().replace(' ','_')}_market_map.html",
        gexf_out=f"exports/{args.company.lower().replace(' ','_')}_market_map.gexf",
    )
    print("[bold]Market map saved:[/bold]")
    for k, v in paths.items():
        print(f"- {k.upper()}: {v}")


def cmd_all(args):
    # Convenience pipeline
    cmd_industry(args)
    cmd_similar(args)
    cmd_emails(args)
    cmd_news(args)
    cmd_swot(args)
    cmd_export(args)
    cmd_marketmap(args)


def build_parser():
    p = argparse.ArgumentParser(prog="br3000", description="Business Rader 3000 CLI")
    p.add_argument("--debug", action="store_true", help="Enable BR_DEBUG=2")

    sub = p.add_subparsers(dest="cmd", required=True)

    def add_company_cmd(name, help_text):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("-c", "--company", required=True, help="Company name (e.g., 'Ford Motor Company')")
        return sp

    # industry
    add_company_cmd("industry", "Lookup industry/sector").set_defaults(func=cmd_industry)

    # similar
    add_company_cmd("similar", "Find similar companies").set_defaults(func=cmd_similar)

    # emails
    sp = add_company_cmd("emails", "Find emails (Hunter or shallow scrape)")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--priority", action="store_true", help="Prioritize by title (CEO, Founder, Sales, Marketing, Procurement)")
    sp.set_defaults(func=cmd_emails)

    # news
    sp = add_company_cmd("news", "Scan funding / M&A / expansion news")
    sp.add_argument("--days", type=int, default=180)
    sp.add_argument("--max", type=int, default=8)
    sp.set_defaults(func=cmd_news)

    # keyword
    sp = add_company_cmd("keyword", "Keyword match (website + news)")
    sp.add_argument("-k", "--keywords", nargs="+", required=True, help="Keywords, e.g. ai saas procurement")
    sp.add_argument("--days", type=int, default=180)
    sp.add_argument("--max", type=int, default=8)
    sp.set_defaults(func=cmd_keyword)

    # swot
    sp = add_company_cmd("swot", "Generate SWOT from news")
    sp.add_argument("--days", type=int, default=180)
    sp.add_argument("--max", type=int, default=12)
    sp.add_argument("--top", type=int, default=5, help="Max items per SWOT bucket")
    sp.set_defaults(func=cmd_swot)

    # export
    sp = add_company_cmd("export", "Export CSV/JSON")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--priority", action="store_true")
    sp.set_defaults(func=cmd_export)

    # market map
    sp = add_company_cmd("marketmap", "Build market map (HTML + GEXF)")
    sp.add_argument("--depth", type=int, default=1)
    sp.add_argument("--max-per-node", type=int, default=8)
    sp.set_defaults(func=cmd_marketmap)

    # all-in-one
    sp = add_company_cmd("all", "Run the full pipeline")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--priority", action="store_true")
    sp.add_argument("--days", type=int, default=180)
    sp.add_argument("--max", type=int, default=8)
    sp.add_argument("--top", type=int, default=5)
    sp.add_argument("--depth", type=int, default=1)
    sp.add_argument("--max-per-node", type=int, default=8)
    sp.set_defaults(func=cmd_all)

    return p


def main():
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if args.debug:
        os.environ["BR_DEBUG"] = "2"

    args.func(args)


if __name__ == "__main__":
    main()
