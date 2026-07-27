"""
scp.py — Supreme Court of Pakistan (SCP) judgment scraper.

Inherits from BaseScraper. Uses Playwright's Chrome channel, stealth patches,
DOM JS option evaluation for ASP.NET dropdowns (2021–2026), automatic year inference,
and in-browser JS fetch with base64 decoding to reliably download PDFs under Cloudflare protection.
"""

import asyncio
import base64
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from playwright.async_api import Page, async_playwright
from scraper.base_scraper import BaseScraper


class SCPScraper(BaseScraper):
    """Scraper for Supreme Court of Pakistan (SCP) reported and latest judgments."""

    CRIMINAL_CASE_TYPES = [
        "Crl.P.L.A.",
        "Crl.A.",
        "Crl.M.A.",
        "Crl.M.Appeal.",
        "Crl.R.P.",
        "Crl.O.P."
    ]

    SEARCH_KEYWORDS = ["criminal", "state", "bail", "fia", "peca", "murder"]

    def __init__(self, keyword: str = "criminal", year: int = 2025, **kwargs):
        super().__init__(keyword=keyword, year=year, **kwargs)

    @property
    def search_url(self) -> str:
        return "https://scp.gov.pk/LatestJudgments.aspx"

    async def run(self) -> list:
        """
        Overridden run loop to force launch with channel='chrome' and stealth script
        to bypass Cloudflare security.
        """
        self.logger.info(
            "Starting SCP scraper for keyword=%r on %s", self.keyword, self.search_url
        )
        downloaded = []

        async with async_playwright() as pw:
            self._playwright = pw
            
            launch_args = ["--no-sandbox"]
            try:
                self._browser = await pw.chromium.launch(
                    headless=self.headless, channel="chrome", args=launch_args
                )
            except Exception as e:
                self.logger.warning("Could not launch installed Chrome channel, falling back: %s", e)
                self._browser = await pw.chromium.launch(headless=self.headless, args=launch_args)

            self._context = await self._browser.new_context(
                accept_downloads=True,
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            # Add stealth patch to context
            await self._context.add_init_script("delete navigator.__proto__.webdriver;")
            
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self.timeout_ms)

            try:
                await self._with_retry(self.submit_search, self._page, self.keyword)

                # Deduplicate collected URLs
                pdf_urls = list(dict.fromkeys(self._collected_pdf_urls))
                self.logger.info("Total unique PDFs to download: %d", len(pdf_urls))

                for url in pdf_urls:
                    dest = await self._download_pdf(url)
                    if dest and dest.exists() and dest.stat().st_size > 0:
                        downloaded.append(dest)

            finally:
                try:
                    await self._context.close()
                    await self._browser.close()
                except Exception:
                    pass

        return downloaded

    async def submit_search(self, page: Page, keyword: str) -> None:
        """
        Visits the SCP LatestJudgments and JudgmentsSearch ASP.NET portals,
        executes case type and keyword queries for the target year, and extracts direct PDF download links.
        """
        # 1. Scrape LatestJudgments.aspx
        self.logger.info("Visiting SCP LatestJudgments page...")
        try:
            await page.goto("https://scp.gov.pk/LatestJudgments.aspx", wait_until="networkidle", timeout=35_000)
            await page.wait_for_timeout(1000)
            await self._extract_links_from_page(page)
        except Exception as e:
            self.logger.warning("Failed to visit LatestJudgments.aspx: %s", e)

        # 2. Iterate through Criminal Case Types on JudgmentsSearch.aspx using JS evaluation
        self.logger.info("Iterating criminal case types on JudgmentsSearch page for year %d...", self.year)
        for ctype in self.CRIMINAL_CASE_TYPES:
            try:
                await page.goto("https://scp.gov.pk/JudgmentsSearch.aspx", wait_until="networkidle", timeout=35_000)
                await page.wait_for_timeout(1000)

                # Use JS evaluation to set dropdowns
                await page.evaluate(f"""() => {{
                    const casetypeSel = document.querySelector('#ContentPlaceHolder1_ddlCaseType');
                    if (casetypeSel) {{
                        casetypeSel.value = '{ctype}';
                        casetypeSel.dispatchEvent(new Event('change'));
                    }}
                    const yearSel = document.querySelector('#ContentPlaceHolder1_ddlCaseYear');
                    if (yearSel) {{
                        yearSel.value = '{self.year}';
                        yearSel.dispatchEvent(new Event('change'));
                    }}
                }}""")

                # Click Search button
                search_btn = await page.query_selector("#ContentPlaceHolder1_btnSearch") or await page.query_selector("input[value*='Search']")
                if search_btn:
                    await search_btn.click()
                    await page.wait_for_timeout(2500)
                    self.logger.info("  Search submitted for Case Type: %s (%d).", ctype, self.year)
                    await self._extract_links_from_page(page)

            except Exception as e:
                self.logger.warning("  Query failed for Case Type %s (%d): %s", ctype, self.year, e)

        # 3. Iterate through Keywords on JudgmentsSearch.aspx using JS evaluation
        self.logger.info("Iterating criminal keywords on JudgmentsSearch page...")
        for kw in self.SEARCH_KEYWORDS:
            try:
                await page.goto("https://scp.gov.pk/JudgmentsSearch.aspx", wait_until="networkidle", timeout=35_000)
                await page.wait_for_timeout(1000)

                await page.evaluate(f"""() => {{
                    const kwInput = document.querySelector('#ContentPlaceHolder1_txtKeywords');
                    if (kwInput) {{
                        kwInput.value = '{kw}';
                        kwInput.dispatchEvent(new Event('input'));
                    }}
                }}""")

                search_btn = await page.query_selector("#ContentPlaceHolder1_btnSearch") or await page.query_selector("input[value*='Search']")
                if search_btn:
                    await search_btn.click()
                    await page.wait_for_timeout(2500)
                    self.logger.info("  Search submitted for Keyword: %s.", kw)
                    await self._extract_links_from_page(page)
            except Exception as e:
                self.logger.warning("  Query failed for Keyword %s: %s", kw, e)

        self.logger.info(
            "SCPScraper: Total unique PDF links collected for year %d: %d",
            self.year, len(self._collected_pdf_urls)
        )

    async def _extract_links_from_page(self, page: Page):
        anchors = await page.query_selector_all("a")
        count = 0
        for a in anchors:
            href = await a.get_attribute("href")
            if href and ("downloads_judgements" in href.lower() or ".pdf" in href.lower()):
                abs_url = urljoin("https://www.supremecourt.gov.pk/", href)
                if abs_url not in self._collected_pdf_urls:
                    self._collected_pdf_urls.append(abs_url)
                    count += 1

        self.logger.info("  Extracted %d total PDF links from page.", count)

    async def extract_pdf_links(self, page: Page) -> list[str]:
        return []

    async def go_to_next_page(self, page: Page) -> bool:
        return False

    def _url_to_filename(self, url: str) -> str:
        basename = url.split("/")[-1]
        # Infer 4-digit year from 2021-2026 range if present, otherwise default to self.year
        match = re.search(r"202[1-6]", basename)
        file_year = match.group() if match else str(self.year)
        return f"{file_year}_SCP_{basename}"

    async def _download_pdf(self, url: str) -> Optional[Path]:
        """
        Overrides BaseScraper._download_pdf to execute a same-origin in-browser fetch() call,
        converting the PDF Blob into a Base64 string.
        """
        filename = self._url_to_filename(url)
        dest = self.downloads_dir / filename

        # Verify existing file is a valid non-empty PDF
        if dest.exists() and dest.stat().st_size > 0:
            try:
                with open(dest, "rb") as f:
                    header = f.read(4)
                if header == b"%PDF":
                    self.logger.debug("Skipping already-downloaded valid PDF: %s", filename)
                    return dest
            except Exception:
                pass
            dest.unlink(missing_ok=True)

        self.logger.info("Downloading %s via same-origin browser fetch ...", url)

        # Ensure page is on www.supremecourt.gov.pk for same-origin fetch
        if "www.supremecourt.gov.pk" not in self._page.url:
            try:
                await self._page.goto("https://www.supremecourt.gov.pk/", wait_until="networkidle", timeout=25_000)
            except Exception:
                pass

        for attempt in range(1, self.max_retries + 1):
            try:
                # Execute same-origin in-browser JS fetch
                b64_data = await self._page.evaluate("""async (pdfUrl) => {
                    try {
                        const res = await fetch(pdfUrl, { mode: 'cors', credentials: 'omit' });
                        if (!res.ok) return null;
                        const blob = await res.blob();
                        return new Promise((resolve) => {
                            const reader = new FileReader();
                            reader.onloadend = () => {
                                const result = reader.result;
                                if (!result || !result.includes(',')) resolve(null);
                                else resolve(result.split(',')[1]);
                            };
                            reader.onerror = () => resolve(null);
                            reader.readAsDataURL(blob);
                        });
                    } catch (e) {
                        return null;
                    }
                }""", url)

                if b64_data:
                    pdf_bytes = base64.b64decode(b64_data)
                    if pdf_bytes.startswith(b"%PDF"):
                        with open(dest, "wb") as f:
                            f.write(pdf_bytes)
                        self.logger.info("Saved -> %s (%d KB)", filename, len(pdf_bytes) // 1024)
                        return dest
                    else:
                        self.logger.warning("Attempt %d/%d downloaded data does not start with %%PDF magic bytes", attempt, self.max_retries)
                else:
                    self.logger.warning("Attempt %d/%d same-origin fetch returned empty/null data", attempt, self.max_retries)

            except Exception as exc:
                self.logger.warning("Attempt %d/%d failed for %s: %s", attempt, self.max_retries, url, exc)
            await asyncio.sleep(self.retry_delay)

        self.logger.error("All download attempts failed for %s", url)
        return None
