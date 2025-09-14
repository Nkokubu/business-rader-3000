from rich import print
from dotenv import load_dotenv
from services.enrichment import get_industry_info
import os
from services.similar import get_similar_companies

def main():
    load_dotenv()
    print("[bold green]Business Rader 3000 — Day 2[/bold green]")
    company = input("Enter a company name: ").strip()
    if not company:
        print("[red]No company name entered. Exiting.[/red]")
        return

    info = get_industry_info(company)
    print("[bold]Industry lookup result:[/bold]")
    print(info)  # e.g. {'industry': 'Software', 'sector': 'Technology'}
    
    sims = get_similar_companies(company, industry_hint=info.get("industry"))
    print("[bold]Similar companies:[/bold]")
    for s in sims:
        name = (s.get("name") or "").strip()
        url = (s.get("website") or "").strip().rstrip("/")
        if not name:
            continue
        print(f"- {name}" + (f" ({url})" if url else ""))


if __name__ == "__main__":
    main()
