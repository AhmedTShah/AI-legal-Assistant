"""
phc.py — Peshawar High Court judgment scraper.

Inherits from BaseScraper. Runs keyword-based searches under year=0 (All Years)
and category=1 (Criminal) to bypass the portal's year-search 500 crashes,
extracts links for years 2024–2026, and downloads them.
"""

import re
from urllib.parse import urljoin
from playwright.async_api import Page
from scraper.base_scraper import BaseScraper


class PHCScraper(BaseScraper):
    """Scraper for the Peshawar High Court judgment portal."""

    def __init__(self, keyword: str = "state", year: int = 2025, **kwargs):
        # We store year in self.year to filter downloads, but search year=0 to avoid crashes
        super().__init__(keyword=keyword, year=year, **kwargs)

    @property
    def search_url(self) -> str:
        return "https://peshawarhighcourt.gov.pk/PHCCMS/reportedJudgments.php"

    async def submit_search(self, page: Page, keyword: str) -> None:
        """
        Submits searches for high-value criminal keywords under All Years,
        and collects PDF links matching the target years (2024–2026).
        """
        # List of keywords to query to get comprehensive coverage
        search_keywords = ["state", "bail", "fia", "peca", "narcotics", "murder"]
        
        for kw in search_keywords:
            self.logger.info("Executing PHC search for keyword: %s ...", kw)
            try:
                # 1. Load search page
                await page.goto(self.search_url, wait_until="load")
                await page.wait_for_selector("#year")
                
                # 2. Select Year = All Years ("0") to avoid HTTP 500 database crashes
                await page.select_option("#year", value="0")
                
                # 3. Select Category = Criminal ("1")
                await page.select_option("#category", value="1")
                
                # 4. Fill keyword
                await page.fill("#txtsearchbyremarks", kw)
                
                # 5. Submit search and wait for navigation
                async with page.expect_navigation(wait_until="networkidle", timeout=25_000) as nav_info:
                    await page.click("input[type='submit'][name='submit']")
                
                self.logger.info("  Search results loaded successfully.")
                
                # 6. Extract matching links from the results
                anchors = await page.query_selector_all("a")
                count = 0
                for a in anchors:
                    href = await a.get_attribute("href")
                    if href and ".pdf" in href.lower():
                        # Resolve absolute URL
                        abs_url = urljoin("https://peshawarhighcourt.gov.pk/PHCCMS/", href)
                        
                        # Filter by year (we only want target year, or range 2024-2026)
                        # Check if target year or target range matches
                        filename = href.split("/")[-1]
                        
                        # We also search the row text for the year if needed, but filename matches are highly accurate
                        # Search for 4-digit years matching 2024, 2025, or 2026 in filename
                        match = re.search(r"202[4-6]", filename)
                        
                        # Fallback: check if row contains the year
                        row_has_year = False
                        try:
                            parent_tr = await a.evaluate_handle("el => el.closest('tr')")
                            if parent_tr:
                                tr_text = await parent_tr.evaluate("el => el.innerText")
                                if str(self.year) in tr_text or any(yr in tr_text for yr in ["2024", "2025", "2026"]):
                                    row_has_year = True
                        except Exception:
                            pass

                        # If filename contains target year, or parent row mentions it, we collect
                        if match and int(match.group()) == self.year or (not match and row_has_year):
                            if abs_url not in self._collected_pdf_urls:
                                self._collected_pdf_urls.append(abs_url)
                                count += 1
                                
                self.logger.info("  Collected %d PDF links for keyword '%s' matching year %d.", count, kw, self.year)
                
            except Exception as e:
                self.logger.warning("  Error executing search for keyword '%s': %s", kw, e)
                
        # De-duplicate collected links
        self._collected_pdf_urls = list(dict.fromkeys(self._collected_pdf_urls))
        self.logger.info(
            "PHC Scraper: Collected %d total unique PDF links for year %d",
            len(self._collected_pdf_urls), self.year
        )

    async def extract_pdf_links(self, page: Page) -> list[str]:
        # Handled in submit_search, return empty to skip base class loop
        return []

    async def go_to_next_page(self, page: Page) -> bool:
        # Traversed all results in single page, return False
        return False

    def _url_to_filename(self, url: str) -> str:
        # e.g., https://peshawarhighcourt.gov.pk/PHCCMS/judgments/Cr.A.-1216-P-of-2025-dismissed-u.pdf -> 2025_PHC_Cr.A.-1216-P-of-2025-dismissed-u.pdf
        basename = url.split("/")[-1]
        return f"{self.year}_PHC_{basename}"
