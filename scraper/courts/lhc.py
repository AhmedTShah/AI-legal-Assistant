"""
lhc.py — Lahore High Court criminal judgment scraper.

Target portal : https://data.lhc.gov.pk/dynamic/approved_judgments_result_new.php?year={year}
Strategy      : Targets the backend search results URL directly. This returns all 
                judgments for a given year on a single page, eliminating the need 
                for complex pagination loops.
                Filters cases to only download criminal-related judgments.

Criminal case type filters (applied to case type or title text):
    "Crl."      — Criminal Misc / Appeal / Revision / Petition
    "Criminal"  — Criminal Proceedings
    "Jail"      — Jail Appeals
    "PECA"      — Cybercrime (Prevention of Electronic Crimes Act)

Usage (standalone):
    python -m scraper.courts.lhc --year 2026
    python -m scraper.courts.lhc --year 2025 --no-headless
"""

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# ── Criminal case type filters ─────────────────────────────────────────────────
CRIMINAL_PREFIXES = (
    "Crl.",         # Crl. Misc, Crl. Appeal, Crl. Revision, Crl. Petition
    "Criminal",     # Criminal Proceedings, Criminal Trial
    "Jail",         # Jail Appeal
    "PECA",         # Prevention of Electronic Crimes Act
)


def _is_criminal(text: str) -> bool:
    """Return True if the text indicates a criminal case type."""
    cleaned = (text or "").strip()
    return any(cleaned.startswith(prefix) or prefix in cleaned for prefix in CRIMINAL_PREFIXES)


class LHCScraper(BaseScraper):
    """
    Scraper for the Lahore High Court dynamic approved judgments.
    """

    def __init__(self, year: int = 2026, **kwargs):
        kwargs.setdefault("keyword", "criminal")
        super().__init__(**kwargs)
        self.year = year

    @property
    def search_url(self) -> str:
        # Querying the backend directly for all judgments of the given year
        return f"https://data.lhc.gov.pk/dynamic/approved_judgments_result_new.php?year={self.year}"

    async def submit_search(self, page: Page, keyword: str) -> None:
        """Navigate directly to the year-specific search result page."""
        self.logger.info("Navigating to dynamic approved judgments page for year %d ...", self.year)
        await page.goto(self.search_url, wait_until="domcontentloaded")
        
        # Wait a few seconds to ensure the page renders
        await page.wait_for_timeout(3000)
        self.logger.info("LHC dynamic judgments page loaded.")

    async def extract_pdf_links(self, page: Page) -> list:
        """
        Extract PDF links from the page.
        Extracts case type and title from table rows to filter for criminal cases.
        """
        rows = await page.query_selector_all("tr")
        urls = []

        for row in rows:
            cells = await row.query_selector_all("td")
            if len(cells) < 7:
                continue

            anchor = await row.query_selector("a[href$='.pdf']")
            if not anchor:
                continue

            href = await anchor.get_attribute("href")
            if not href:
                continue

            # In the dynamic table:
            # - Cell index 1 (2nd cell) is Case Type / Number
            # - Cell index 2 (3rd cell) is Party Title
            case_type = await cells[1].inner_text()
            title = await cells[2].inner_text()
            combined_text = f"{case_type} {title}"

            if not _is_criminal(combined_text):
                self.logger.debug("Skipping non-criminal case: %s", combined_text.replace("\n", " ").strip())
                continue

            absolute = self.make_absolute(page.url, href.strip())
            urls.append(absolute)
            self.logger.info("Found criminal case: %s | %s", combined_text.replace("\n", " ").strip(), absolute)

        self.logger.info("Total criminal PDFs found for year %d: %d", self.year, len(urls))
        return urls

    async def go_to_next_page(self, page: Page) -> bool:
        """
        No pagination needed since all results for the year are on a single page.
        """
        return False


# ── CLI ────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LHC criminal judgment scraper — downloads PDFs to /downloads/"
    )
    parser.add_argument("--year",          type=int,  default=2026, help="Target year to scrape")
    parser.add_argument("--downloads-dir", type=Path, default=None, help="PDF output directory")
    parser.add_argument("--no-headless",   action="store_true",     help="Show browser UI")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    scraper = LHCScraper(
        year=args.year,
        downloads_dir=args.downloads_dir,
        headless=not args.no_headless,
    )
    downloaded = await scraper.run()
    print(f"\nDownload complete — {len(downloaded)} criminal PDF(s) saved for year {args.year}.")
    for p in downloaded:
        print(f"   {p}")


if __name__ == "__main__":
    asyncio.run(main())
