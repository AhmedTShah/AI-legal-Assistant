"""
base_scraper.py — Shared Playwright async base class for all court scrapers.

All court-specific scrapers (lhc.py, shc.py, etc.) inherit from BaseScraper
and override the abstract methods to customise behaviour for each portal.
"""

import asyncio
import logging
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DOWNLOADS_DIR = Path(__file__).parent.parent / "downloads"
DEFAULT_TIMEOUT_MS    = 30_000
DEFAULT_MAX_RETRIES   = 3
DEFAULT_RETRY_DELAY_S = 5
DEFAULT_MAX_PAGES     = 50


class BaseScraper(ABC):
    """
    Async base scraper built on Playwright Chromium.

    Subclasses must implement:
        - search_url          (property)
        - submit_search()
        - extract_pdf_links()
        - go_to_next_page()
    """

    def __init__(
        self,
        keyword: str,
        downloads_dir: Optional[Path] = None,
        headless: bool = True,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY_S,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self.keyword       = keyword
        self.downloads_dir = downloads_dir or DEFAULT_DOWNLOADS_DIR
        self.headless      = headless
        self.max_pages     = max_pages
        self.max_retries   = max_retries
        self.retry_delay   = retry_delay
        self.timeout_ms    = timeout_ms

        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(self.__class__.__name__)

        self._playwright: Optional[Playwright]     = None
        self._browser: Optional[Browser]           = None
        self._context: Optional[BrowserContext]    = None
        self._page: Optional[Page]                 = None
        self._collected_pdf_urls: list[str]        = []

    # ── Abstract interface ────────────────────────────────────────────────────
    @property
    @abstractmethod
    def search_url(self) -> str:
        """Base search URL for this court's judgment portal."""

    @abstractmethod
    async def submit_search(self, page: Page, keyword: str) -> None:
        """Navigate, fill keyword, submit form and wait for results."""

    @abstractmethod
    async def extract_pdf_links(self, page: Page) -> list:
        """Return list of absolute PDF URLs from the current results page."""

    @abstractmethod
    async def go_to_next_page(self, page: Page) -> bool:
        """Navigate to next results page. Returns False when no more pages."""

    # ── Public entry point ────────────────────────────────────────────────────
    async def run(self) -> list:
        """Full pipeline: launch browser -> search -> paginate -> download PDFs."""
        self.logger.info(
            "Starting scraper for keyword=%r on %s", self.keyword, self.search_url
        )
        downloaded = []

        async with async_playwright() as pw:
            self._playwright = pw
            self._browser = await pw.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
                accept_downloads=True,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self.timeout_ms)

            try:
                await self._with_retry(self.submit_search, self._page, self.keyword)

                page_num = 1
                while page_num <= self.max_pages:
                    self.logger.info("Scraping results page %d ...", page_num)
                    links = await self._with_retry(self.extract_pdf_links, self._page)
                    self.logger.info(
                        "Found %d PDF link(s) on page %d", len(links), page_num
                    )
                    self._collected_pdf_urls.extend(links)

                    has_next = await self._with_retry(self.go_to_next_page, self._page)
                    if not has_next:
                        self.logger.info("No more pages — pagination complete.")
                        break
                    page_num += 1

                if page_num > self.max_pages:
                    self.logger.warning(
                        "Reached max_pages cap (%d). Stopping early.", self.max_pages
                    )

                unique_urls = list(dict.fromkeys(self._collected_pdf_urls))
                self.logger.info("Total unique PDFs to download: %d", len(unique_urls))
                for url in unique_urls:
                    path = await self._download_pdf(url)
                    if path:
                        downloaded.append(path)

            except Exception as exc:
                self.logger.error("Scraper run failed: %s", exc, exc_info=True)
            finally:
                await self._context.close()
                await self._browser.close()

        self.logger.info("Scrape complete. Downloaded %d PDF(s).", len(downloaded))
        return downloaded

    # ── Retry wrapper ─────────────────────────────────────────────────────────
    async def _with_retry(self, coro_fn, *args, **kwargs):
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await coro_fn(*args, **kwargs)
            except (PlaywrightTimeoutError, Exception) as exc:
                last_exc = exc
                self.logger.warning(
                    "Attempt %d/%d failed for %s: %s",
                    attempt, self.max_retries, coro_fn.__name__, exc,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)
        raise last_exc

    # ── PDF download ──────────────────────────────────────────────────────────
    async def _download_pdf(self, url: str) -> Optional[Path]:
        """Download a single PDF via httpx. Skips already-downloaded files."""
        filename = self._url_to_filename(url)
        dest = self.downloads_dir / filename

        if dest.exists():
            self.logger.debug("Skipping already-downloaded: %s", filename)
            return dest

        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info("[%d/%d] Downloading %s ...", attempt, self.max_retries, url)
                async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                    response = await client.get(url)
                    response.raise_for_status()

                    content_type = response.headers.get("content-type", "")
                    if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                        self.logger.warning(
                            "Unexpected content-type %r for %s — skipping.",
                            content_type, url,
                        )
                        return None

                    dest.write_bytes(response.content)
                self.logger.info("Saved -> %s", dest)
                return dest

            except httpx.HTTPStatusError as exc:
                self.logger.error("HTTP %s for %s", exc.response.status_code, url)
                return None
            except Exception as exc:
                self.logger.warning("Download attempt %d failed: %s", attempt, exc)
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)

        self.logger.error("All download attempts failed for %s", url)
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _url_to_filename(url: str) -> str:
        parsed = urlparse(url)
        raw  = Path(parsed.path).name or "judgment.pdf"
        safe = re.sub(r'[^\w\-.]', '_', raw)
        if not safe.lower().endswith(".pdf"):
            safe += ".pdf"
        return safe

    @staticmethod
    def make_absolute(base_url: str, href: str) -> str:
        return urljoin(base_url, href)
