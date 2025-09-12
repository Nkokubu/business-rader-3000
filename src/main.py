from rich import print
from dotenv import load_dotenv
import os

def main():
    load_dotenv()  # loads variables from .env if present
    print("[bold green]Business Rader 3000 — Day 1[/bold green]")
    company = input("Enter a company name: ").strip()
    if not company:
        print("[red]No company name entered. Exiting.[/red]")
        return
    print(f"[cyan]You entered:[/cyan] {company}")
    # Placeholder: future steps (search, enrichment, etc.)

if __name__ == "__main__":
    main()
