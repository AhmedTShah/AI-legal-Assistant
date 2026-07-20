"""
phc.py — Peshawar High Court judgment scraper (stub).

Inherits from BaseScraper. Implement submit_search(), extract_pdf_links(),
and go_to_next_page() once the PHC portal selectors are confirmed.

Target portal: https://phc.gov.pk  (update URL as needed)
"""

from playwright.async_api import Page
from scraper.base_scraper import BaseScraper


class PHCScraper(BaseScraper):
    """Stub scraper for the Peshawar High Court judgment portal."""

    def __init__(self, keyword: str = "PECA", **kwargs):
        super().__init__(keyword=keyword, **kwargs)

    @property
    def search_url(self) -> str:
        return "https://phc.gov.pk/judgments"  # TODO: confirm live URL

    async def submit_search(self, page: Page, keyword: str) -> None:
        raise NotImplementedError("PHC submit_search not yet implemented.")

    async def extract_pdf_links(self, page: Page) -> list[str]:
        raise NotImplementedError("PHC extract_pdf_links not yet implemented.")

    async def go_to_next_page(self, page: Page) -> bool:
        raise NotImplementedError("PHC go_to_next_page not yet implemented.")
