from rich import print
from dotenv import load_dotenv

# Day 2
from services.enrichment import get_industry_info
# Day 3
from services.similar import get_similar_companies
# Day 4 & 5
from services.contacts import find_emails_for_company, filter_contacts_by_title, resolve_company_domain
# Day 6 (export)
from services.exporter import build_rows, export_csv, export_json
# Day 6 (news)
from services.news import scan_news
# Day 7 (keyword matching)
from services.keyword_match import flag_business, expand_keywords, match_keywords
from services.swot import generate_swot_from_news
from services.market_graph import build_and_render_market_map
from services.similar import get_similar_companies



def main():
    load_dotenv()
    print("[bold green]Business Rader 3000 — Day 4-7[/bold green]")
    company = input("Enter a company name: ").strip()
    if not company:
        print("[red]No company name entered. Exiting.[/red]")
        return

    # ---- Day 2: Industry lookup ----
    info = get_industry_info(company)
    if info.get("sector") == "Consumer Cyclical":
        info["sector"] = "Consumer Discretionary"
    print("[bold]Industry lookup result:[/bold]")
    print(info)

    # ---- Day 3: Similar companies ----
    sims = get_similar_companies(company, industry_hint=info.get("industry"))
    print("[bold]Similar companies:[/bold]")
    if not sims:
        print("- (none)")
    else:
        for s in sims:
            name = (s.get("name") or "").strip()
            url = (s.get("website") or "").strip().rstrip("/")
            if not name:
                continue
            print(f"- {name}" + (f" ({url})" if url else ""))

    # ---- Day 4: Emails (Hunter or shallow scrape) ----
    # If you later return a website from enrichment, set website_hint = info.get("website")
    website_hint = None
    emails = find_emails_for_company(company, website_hint=website_hint, limit=10)

    # ---- Day 11: Similar Market Mapping ----
    # One hop (seed -> peers). Increase max_depth=2 to include peers-of-peers.
    map_paths = build_and_render_market_map(
        seed_company=company,
        get_similar=lambda name: get_similar_companies(name, industry_hint=info.get("industry")),
        max_depth=1,          # try 2 for a larger map
        max_per_company=8,    # cap per node
        html_out=f"exports/{company.lower().replace(' ','_')}_market_map.html",
        gexf_out=f"exports/{company.lower().replace(' ','_')}_market_map.gexf",
    )
    print("[bold]Market map saved:[/bold]")
    for k, v in map_paths.items():
        print(f"- {k.upper()}: {v}")

    # ---- Day 5: Prioritize by title ----
    prioritized = filter_contacts_by_title(emails, top_n=10, min_score=1)
    print("[bold]Priority contacts (best titles first):[/bold]")
    if not prioritized:
        print("- (none matched priority titles)")
    else:
        for c in prioritized:
            addr = (c.get("email") or "").strip()
            name = (c.get("name") or "").strip()
            title = (c.get("title") or "").strip()
            src = (c.get("source") or "").strip()
            score = c.get("score", 0)
            line = f"- {addr}"
            if name:
                line += f" | {name}"
            if title:
                line += f" — {title}"
            line += f"  [score {score}]"
            if src:
                line += f"  [{src}]"
            print(line)

    # ---- Day 6: News & Press Releases ----
    print("[bold]Recent news (funding / M&A / expansion):[/bold]")
    news = scan_news(company, days=180, max_results=8)
    if not news:
        print("- (none)")
    else:
        for n in news:
            line = f"- [{n['kind']}] {n['summary']}"
            if n.get("date"):
                line += f" ({n['date']})"
            line += f"  {n['url']}"
            print(line)

    # ---- Day 6+: SWOT from news ----
    swot = generate_swot_from_news(company, news, max_items_per_bucket=5)
    print("[bold]SWOT (from recent news):[/bold]")
    for bucket in ("Strengths", "Weaknesses", "Opportunities", "Threats"):
        print(f"- {bucket}:")
        if not swot[bucket]:
            print("  • (none)")
        else:
            for item in swot[bucket]:
                print(f"  • {item}")

    # Save a swot-only JSON (optional)
    from services.exporter import export_json
    swot_json_path = export_json(
        [{"company_name": company, "swot": swot}],
        basename=f"{company.lower().replace(' ','_')}_swot"
    )
    print(f"- SWOT JSON: {swot_json_path}")

    # ---- Day 7: Keyword Matching (ask user, then evaluate) ----
    raw = input("Enter interest keywords (comma-separated, e.g., ai, saas, crm): ").strip()
    interest = [k.strip() for k in raw.split(",") if k.strip()] if raw else []

    if interest:
        # Optional: check matches in NEWS titles
        expanded = expand_keywords(interest)
        news_text = " ".join(n.get("title", "") for n in news)
        news_hits = match_keywords(news_text, expanded)
        if news_hits["matched"]:
            print("[bold]Keyword match in NEWS:[/bold]", news_hits["matched"])

        # Website/domain resolution and on-site keyword flag
        website_hint = None  # change to info.get("website") if you add it in enrichment
        domain = resolve_company_domain(company, website_hint=website_hint)
        flagged = flag_business(company, url_or_domain=(domain or website_hint), include_keywords=interest)
        print("[bold]Keyword match (website scan):[/bold]")
        print({"flag": flagged["flag"], "score": flagged["score"], "matched": flagged["matched_keywords"]})
        if flagged["evidence"]:
            print("[bold]Evidence:[/bold]")
            for ev in flagged["evidence"]:
                print(f"- {ev['url']} — {ev['snippet']}")

    # ---- Day 6: Export (CSV + JSON) ----
    # Use domain to create a nice URL when no explicit website is available.
    domain_hint = resolve_company_domain(company, website_hint=website_hint)
    rows = build_rows(
        company_name=company,
        industry=info.get("industry"),
        website_hint=website_hint,
        domain_hint=domain_hint,
        contacts=emails,  # or `prioritized` if you only want the ranked subset
    )
    base = company.lower().replace(" ", "_")
    csv_path = export_csv(rows, basename=base)
    json_path = export_json(rows, basename=base)
    print("[bold]Saved files:[/bold]")
    print(f"- CSV : {csv_path}")
    print(f"- JSON: {json_path}")


if __name__ == "__main__":
    main()


