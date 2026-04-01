"""
process_paper.py
----------------
Mobile → GitHub → Notion research pipeline for SSRN papers.

Reads PAPER_URL from env, scrapes the SSRN page for its title,
appends to data/papers.json, then creates a Notion page.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

PAPER_URL = os.environ.get("PAPER_URL", "").strip()
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")

DATA_FILE = Path("data/papers.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def scrape_title(url: str) -> str:
    """
    Attempt to scrape the paper title from an SSRN page.
    Falls back to the URL string if anything goes wrong.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Primary selector: SSRN uses this class for the paper title
        title_tag = soup.find("h1", class_="title")
        if title_tag and title_tag.get_text(strip=True):
            return title_tag.get_text(strip=True)

        # Fallback 1: Open Graph meta tag
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content", "").strip():
            return og_title["content"].strip()

        # Fallback 2: plain <title> tag (strip " :: SSRN" suffix if present)
        if soup.title and soup.title.string:
            raw = soup.title.string.strip()
            return raw.split(" :: ")[0].strip() or raw

    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Could not scrape title ({exc}); using URL as title.")

    return url  # last-resort fallback


def load_papers() -> list[dict]:
    """Load existing papers from JSON, or return an empty list."""
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
                return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            print("⚠️  papers.json is malformed; starting fresh.")
    return []


def save_papers(papers: list[dict]) -> None:
    """Persist the papers list to disk."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as fh:
        json.dump(papers, fh, indent=2, ensure_ascii=False)
    print(f"✅  Saved {len(papers)} paper(s) to {DATA_FILE}")


def is_duplicate(papers: list[dict], url: str) -> bool:
    """Return True if this URL was already recorded."""
    return any(p.get("url") == url for p in papers)


def create_notion_page(title: str, url: str) -> None:
    """Create a new page in the configured Notion database."""
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("⚠️  Notion credentials missing; skipping Notion sync.")
        return

    endpoint = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {
                "title": [{"text": {"content": title}}]
            },
            "Link": {
                "url": url
            },
        },
    }

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        page_id = resp.json().get("id", "unknown")
        print(f"✅  Notion page created (id: {page_id})")
    except requests.HTTPError as exc:
        print(f"❌  Notion API error {exc.response.status_code}: {exc.response.text}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"❌  Unexpected Notion error: {exc}")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    if not PAPER_URL:
        print("❌  PAPER_URL environment variable is empty. Aborting.")
        sys.exit(1)

    print(f"🔗  Processing URL: {PAPER_URL}")

    # 1. Load existing data
    papers = load_papers()

    # 2. Duplicate guard
    if is_duplicate(papers, PAPER_URL):
        print(f"ℹ️   URL already in papers.json — skipping duplicate.")
        sys.exit(0)

    # 3. Scrape title
    title = scrape_title(PAPER_URL)
    print(f"📄  Title: {title}")

    # 4. Build record
    record = {
        "title": title,
        "url": PAPER_URL,
        "date_added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # 5. Persist to JSON
    papers.append(record)
    save_papers(papers)

    # 6. Sync to Notion
    create_notion_page(title, PAPER_URL)

    print("🎉  Pipeline complete.")


if __name__ == "__main__":
    main()
