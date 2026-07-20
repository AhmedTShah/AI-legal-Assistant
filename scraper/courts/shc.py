"""
shc.py — Sindh High Court judgment scraper (stub).

Inherits from BaseScraper. Implement submit_search(), extract_pdf_links(),
and go_to_next_page() once the SHC portal selectors are confirmed.

Target portal: https://www.shc.gov.pk  (update URL as needed)
"""

from playwright.async_api import Page
from scraper.base_scraper import BaseScraper


class SHCScraper(BaseScraper):
    """Stub scraper for the Sindh High Court judgment portal."""

    def __init__(self, keyword: str = "PECA", **kwargs):
        super().__init__(keyword=keyword, **kwargs)

    @property
    def search_url(self) -> str:
        return "https://www.shc.gov.pk/judgments"  # TODO: confirm live URL

    async def submit_search(self, page: Page, keyword: str) -> None:
        raise NotImplementedError("SHC submit_search not yet implemented.")

    async def extract_pdf_links(self, page: Page) -> list[str]:
        raise NotImplementedError("SHC extract_pdf_links not yet implemented.")

    async def go_to_next_page(self, page: Page) -> bool:
        raise NotImplementedError("SHC go_to_next_page not yet implemented.")
