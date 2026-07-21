"""
shc.py — Sindh High Court judgment scraper.

Inherits from BaseScraper. Automatically queries all major criminal case type codes
on the SHC Caselaw portal for the target year, extracts all PDF download links,
and saves them with structured filenames.
"""

from playwright.async_api import Page
from scraper.base_scraper import BaseScraper


class SHCScraper(BaseScraper):
    """Scraper for the Sindh High Court reported judgments portal."""

    def __init__(self, keyword: str = "criminal", year: int = 2026, **kwargs):
        super().__init__(keyword=keyword, year=year, **kwargs)

    @property
    def search_url(self) -> str:
        return "https://caselaw.shc.gov.pk/caselaw/search-all/search"

    async def submit_search(self, page: Page, keyword: str) -> None:
        """
        Runs the search query for all major criminal category codes for the target year.
        Accumulates all PDF URLs directly into self._collected_pdf_urls.
        """
        # List of high-value criminal category codes in the SHC dropdown
        casetypes = [
            "202",  # Criminal Appeal
            "198",  # Criminal Miscellaneous
            "9",    # Cr. Revision
            "59",   # Spl. Criminal Bail
            "17",   # Cr. Miscellaneous (other)
            "11",   # Cr.Appeal
            "39",   # Spl. cr. Bail
            "22",   # Spl.Cr.A.T.A.
            "12",   # Spl. Cr. A.
        ]

        for code in casetypes:
            self.logger.info("Executing search for case type code %s ...", code)
            
            # Go to the search landing page to reset state completely
            await page.goto(self.search_url, wait_until="load")
            await page.wait_for_selector("#STD_COURTS")
            
            # 1. Select Court (1 = Sindh High Court, Karachi)
            await page.select_option("#STD_COURTS", value="1")
            
            # 2. Select Case Type
            await page.select_option("#STD_CASETYPES", value=code)
            
            # 3. Enter Year
            await page.fill("#CASEYEAR", str(self.year))
            
            # 4. Click Search
            await page.click("#AdvanceSearch")
            
            # 5. Wait for loaders and table
            try:
                # Wait for loaders to hide or table rows to appear
                await page.wait_for_selector("#tblExport tbody tr", timeout=20_000)
            except Exception as e:
                self.logger.warning("Timeout waiting for table rows for code %s: %s", code, e)
                continue
                
            # Check if there are no records
            first_row = await page.query_selector("#tblExport tbody tr")
            if first_row:
                row_text = await first_row.inner_text()
                if "no data available" in row_text.lower() or "no matching records" in row_text.lower():
                    self.logger.info("No matching records found for case type code %s", code)
                    continue
            
            # Change page size to "All" (-1) if the selector is rendered
            length_selector = 'select[name="tblExport_length"]'
            if await page.query_selector(length_selector):
                self.logger.info("Setting table length to 'All' (-1) to fetch all rows on single page")
                await page.select_option(length_selector, value="-1")
                # Wait for loader to hide
                await page.wait_for_timeout(1000)
                await page.wait_for_selector("#bg_screen", state="hidden", timeout=10_000)
            
            # Extract links
            rows = await page.query_selector_all("#tblExport tbody tr")
            count = 0
            for r in rows:
                anchors = await r.query_selector_all("a")
                for a in anchors:
                    href = await a.get_attribute("href")
                    if href and "view-file/" in href:
                        abs_url = self.make_absolute("https://caselaw.shc.gov.pk/caselaw/", href)
                        self._collected_pdf_urls.append(abs_url)
                        count += 1
            self.logger.info("Extracted %d PDF links for case type code %s", count, code)
            
        # De-duplicate collected links
        self._collected_pdf_urls = list(dict.fromkeys(self._collected_pdf_urls))
        self.logger.info(
            "Collected %d total unique PDF links across all criminal categories for year %d", 
            len(self._collected_pdf_urls), self.year
        )

    async def extract_pdf_links(self, page: Page) -> list[str]:
        # Handled in submit_search to combine multiple queries, return empty to skip base class loop
        return []

    async def go_to_next_page(self, page: Page) -> bool:
        # All rows loaded in a single page via Length dropdown, pagination bypass
        return False

    def _url_to_filename(self, url: str) -> str:
        # e.g., https://caselaw.shc.gov.pk/caselaw/view-file/MjcyODQzY2Ztcy1kYzgz -> 2025_SHC_MjcyODQzY2Ztcy1kYzgz.pdf
        code = url.split("/")[-1]
        return f"{self.year}_SHC_{code}.pdf"
