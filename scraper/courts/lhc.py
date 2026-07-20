"""
lhc.py — Lahore High Court judgment scraper.

Target portal : https://www.lhc.gov.pk/case-law
Default keyword: PECA

Usage (standalone):
    python -m scraper.courts.lhc --keyword "PECA" --pages 10
"""

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class LHCScraper(BaseScraper):
    """
    Concrete scraper for the Lahore High Court case-law search portal.

    CSS selectors below match the current portal markup.
    Update them if the site is redesigned.
    """

    SEARCH_INPUT_SELECTOR  = "input[name='search'], input[type='text'], #search-keyword"
    SEARCH_BUTTON_SELECTOR = "button[type='submit'], input[type='submit'], .search-btn"
    RESULTS_CONTAINER_SEL  = ".case-law-results, .judgment-list, table.results, #results"
    PDF_LINK_SELECTOR      = "a[href$='.pdf'], a[href*='/download'], a[href*='judgment']"
    NEXT_PAGE_SELECTOR     = "a.next-page, a[rel='next'], li.next > a, .pagination .next"

    def __init__(self, keyword: str = "PECA", **kwargs):
        super().__init__(keyword=keyword, **kwargs)

    @property
    def search_url(self) -> str:
        return "https://www.lhc.gov.pk/case-law"

    async def submit_search(self, page: Page, keyword: str) -> None:
        """Navigate to LHC search page, fill keyword, and submit."""
        self.logger.info("Navigating to LHC search portal ...")
        await page.goto(self.search_url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(self.SEARCH_INPUT_SELECTOR, timeout=15_000)
        except Exception:
            self.logger.warning("Primary search input not found — trying generic text input.")
            await page.wait_for_selector("input[type='text']", timeout=10_000)

        await page.fill(self.SEARCH_INPUT_SELECTOR, keyword)
        self.logger.info("Filled search box with keyword=%r", keyword)

        try:
            await page.click(self.SEARCH_BUTTON_SELECTOR)
        except Exception:
            self.logger.info("Submit button not found — pressing Enter instead.")
            await page.keyboard.press("Enter")

        try:
            await page.wait_for_selector(self.RESULTS_CONTAINER_SEL, timeout=20_000)
        except Exception:
            await page.wait_for_load_state("networkidle", timeout=20_000)

        self.logger.info("Search submitted — results page loaded.")

    async def extract_pdf_links(self, page: Page) -> list:
        """Find all PDF anchor tags on the current results page."""
        anchors = await page.query_selector_all(self.PDF_LINK_SELECTOR)
        urls = []

        for anchor in anchors:
            href = await anchor.get_attribute("href")
            if not href:
                continue
            absolute = self.make_absolute(page.url, href.strip())
            if absolute.lower().endswith(".pdf") or "/download" in absolute.lower():
                urls.append(absolute)

        self.logger.debug("Extracted %d PDF link(s) from %s", len(urls), page.url)
        return urls

    async def go_to_next_page(self, page: Page) -> bool:
        """Click the 'Next' pagination link if available."""
        try:
            next_btn = await page.query_selector(self.NEXT_PAGE_SELECTOR)
            if next_btn is None:
                return False

            is_disabled = await next_btn.get_attribute("aria-disabled")
            if is_disabled and is_disabled.lower() == "true":
                return False

            await next_btn.click()
            await page.wait_for_load_state("networkidle", timeout=20_000)
            await page.wait_for_selector(self.RESULTS_CONTAINER_SEL, timeout=15_000)
            return True

        except Exception as exc:
            self.logger.info("Pagination ended or failed: %s", exc)
            return False


# ── CLI ────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LHC judgment scraper — downloads PDFs to /downloads/"
    )
    parser.add_argument("--keyword",      default="PECA",  help="Search keyword")
    parser.add_argument("--pages",        type=int, default=10, help="Max result pages")
    parser.add_argument("--downloads-dir", type=Path, default=None, help="PDF output dir")
    parser.add_argument("--no-headless",  action="store_true", help="Show browser UI")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    scraper = LHCScraper(
        keyword=args.keyword,
        downloads_dir=args.downloads_dir,
        headless=not args.no_headless,
        max_pages=args.pages,
    )
    downloaded = await scraper.run()
    print(f"\nDownload complete — {len(downloaded)} PDF(s) saved.")
    for p in downloaded:
        print(f"   {p}")


if __name__ == "__main__":
    asyncio.run(main())
