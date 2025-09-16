from rich import print
from dotenv import load_dotenv

from services.enrichment import get_industry_info
from services.similar import get_similar_companies
from services.contacts import find_emails_for_company, filter_contacts_by_title


def main():
    load_dotenv()
    print("[bold green]Business Rader 3000 — Day 4[/bold green]")
    company = input("Enter a company name: ").strip()
    if not company:
        print("[red]No company name entered. Exiting.[/red]")
        return

    # Day 2 — industry lookup
    info = get_industry_info(company)
    # Optional: normalize Yahoo's label
    if info.get("sector") == "Consumer Cyclical":
        info["sector"] = "Consumer Discretionary"
    print("[bold]Industry lookup result:[/bold]")
    print(info)

    # Day 3 — similar companies
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

    # Day 4 — emails (Hunter.io or shallow site scrape)
    # If your enrichment returns a website later, pass it here; for now keep None.
    website_hint = None  # change to info.get("website") if you add it to enrichment
    emails = find_emails_for_company(company, website_hint=website_hint, limit=10)

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




if __name__ == "__main__":
    main()

