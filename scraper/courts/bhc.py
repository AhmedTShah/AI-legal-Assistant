"""
bhc.py — Balochistan High Court judgment scraper.

Inherits from BaseScraper. Automatically iterates through all judges on the BHC portal,
navigates to their reported and significant judgments pages for the target year,
extracts all PDF download links, and saves them with structured filenames.
"""

from urllib.parse import urljoin, urlparse
from playwright.async_api import Page
from scraper.base_scraper import BaseScraper


class BHCScraper(BaseScraper):
    """Scraper for the Balochistan High Court reported and significant judgments."""

    def __init__(self, keyword: str = "criminal", year: int = 2026, **kwargs):
        super().__init__(keyword=keyword, year=year, **kwargs)

    @property
    def search_url(self) -> str:
        return "https://bhc.gov.pk/resources/judgments"

    async def submit_search(self, page: Page, keyword: str) -> None:
        """
        Iterates through all judges, constructs the target year URLs for both reported
        and significant judgments, and extracts the PDF download links.
        """
        self.logger.info("Navigating to BHC main judgments page to collect judges...")
        await page.goto(self.search_url, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # Extract all judge links
        anchors = await page.query_selector_all('a[href*="/justice-"]')
        judge_names = []
        for a in anchors:
            href = await a.get_attribute("href")
            if href:
                parsed = urlparse(href)
                path = parsed.path
                if "/resources/judgments/justice-" in path:
                    # Extract the judge segment (e.g. justice-muhammad-kamran-khan-malakhail)
                    parts = path.split("/")
                    jname = next((p for p in parts if p.startswith("justice-")), None)
                    if jname and jname not in judge_names:
                        judge_names.append(jname)

        self.logger.info("Found %d BHC judge profiles to scrape.", len(judge_names))
        if not judge_names:
            self.logger.warning("No judge profiles found on the main page.")
            return

        # For each judge, check reported and significant judgments for the target year
        for idx, judge_name in enumerate(judge_names, 1):
            self.logger.info("[%d/%d] Scraping judge: %s", idx, len(judge_names), judge_name)

            # Check both reported and significant judgments
            for jg_type in ["reported-judgments", "significant-judgments"]:
                # Construct target year URL directly
                target_url = f"https://bhc.gov.pk/resources/judgments/{judge_name}/{jg_type}/{self.year}"
                self.logger.info("  Visiting: %s", target_url)

                try:
                    await page.goto(target_url, wait_until="networkidle")
                    await page.wait_for_timeout(1000)

                    # Check if there are judgment boxes on the page
                    boxes = await page.query_selector_all(".judgmentbox")
                    if not boxes:
                        self.logger.debug("    No judgments found for year %d", self.year)
                        continue

                    self.logger.info("    Found %d judgment(s) on page.", len(boxes))
                    count = 0
                    for box in boxes:
                        # Extract PDF link from class popup data-src attribute
                        link_el = await box.query_selector("a.popup")
                        if link_el:
                            data_src = await link_el.get_attribute("data-src")
                            if data_src:
                                # Resolve to absolute URL if needed
                                abs_url = urljoin("https://bhc.gov.pk/", data_src)
                                self._collected_pdf_urls.append(abs_url)
                                count += 1
                                self.logger.debug("      Collected URL: %s", abs_url)

                    self.logger.info("    Successfully collected %d PDF links.", count)

                except Exception as e:
                    self.logger.warning("    Error scraping %s: %s", target_url, e)

        # De-duplicate collected links
        self._collected_pdf_urls = list(dict.fromkeys(self._collected_pdf_urls))
        self.logger.info(
            "Collected %d total unique PDF links for BHC for year %d",
            len(self._collected_pdf_urls), self.year
        )

    async def extract_pdf_links(self, page: Page) -> list[str]:
        # Handled in submit_search to combine multiple queries, return empty to skip base class loop
        return []

    async def go_to_next_page(self, page: Page) -> bool:
        # All pages traversed in submit_search, return False
        return False

    def _url_to_filename(self, url: str) -> str:
        # e.g., https://bhc.gov.pk/media/judgments/1924.pdf -> 2025_BHC_1924.pdf
        basename = url.split("/")[-1]
        stem = basename.replace(".pdf", "")
        return f"{self.year}_BHC_{stem}.pdf"
