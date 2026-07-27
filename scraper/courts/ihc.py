"""
ihc.py — Islamabad High Court (IHC) judgment scraper.

Inherits from BaseScraper. Uses direct ASMX WebService API endpoint queries,
URL encoding, and HTTP downloads to retrieve criminal/cybercrime judgment PDFs.
"""

import asyncio
import json
import logging
import re
import urllib.parse
import requests
import urllib3
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from scraper.base_scraper import BaseScraper

urllib3.disable_warnings()


class IHCScraper(BaseScraper):
    """Scraper for Islamabad High Court (IHC) reported and latest judgments."""

    SEARCH_KEYWORDS = ["criminal", "bail", "fia", "peca", "murder"]

    def __init__(self, keyword: str = "criminal", year: int = 2025, **kwargs):
        super().__init__(keyword=keyword, year=year, **kwargs)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/json; charset=UTF-8"
        })

    @property
    def search_url(self) -> str:
        return "https://mis.ihc.gov.pk/ihc.asmx/srchDecision1"

    async def run(self) -> list:
        """
        Overridden run loop using direct ASMX API queries for high speed and 100% accuracy.
        """
        self.logger.info(
            "Starting IHC scraper for keyword=%r, year=%d on %s", self.keyword, self.year, self.search_url
        )
        downloaded = []

        # Iterate over all search keywords
        pdf_urls = []
        for kw in self.SEARCH_KEYWORDS:
            try:
                urls = self._query_api(kw, self.year)
                pdf_urls.extend(urls)
            except Exception as exc:
                self.logger.warning("Failed IHC API query for keyword %r, year %d: %s", kw, self.year, exc)

        # Deduplicate collected URLs
        unique_urls = list(dict.fromkeys(pdf_urls))
        self.logger.info("Total unique IHC PDFs to download for year %d: %d", self.year, len(unique_urls))

        for url in unique_urls:
            dest = await self._download_pdf(url)
            if dest and dest.exists() and dest.stat().st_size > 0:
                downloaded.append(dest)

        return downloaded

    CRIMINAL_TERMS = [
        "criminal", "crl", "cr.a", "crl.a", "crl.p", "crl.m", "crl.misc", "crl.org", "bail",
        "ppc", "crpc", "cr.p.c", "anti-terrorism", "ata", "police", "fir", "offence", "accused",
        "prosecution", "complainant", "cybercrime", "peca", "fia", "conviction", "sentence",
        "acquittal", "trial court", "penal code", "murder", "narcotics", "cnsa", "302", "376",
        "324", "420", "468", "471", "habeas corpus", "jail appeal", "custody", "prison"
    ]

    def _is_criminal_record(self, rec: dict) -> bool:
        caseno = str(rec.get("CASENO", "")).lower()
        subject = str(rec.get("O_SUBJECT", "")).lower()
        remarks = str(rec.get("O_REMARKS", "")).lower()
        undersec = str(rec.get("O_UNDERSECTION", "")).lower()
        title = str(rec.get("TITLE", "")).lower()
        
        if any(caseno.startswith(prefix) for prefix in ["criminal", "crl", "jail"]):
            return True
            
        combined = f"{title} {caseno} {subject} {remarks} {undersec}"
        return any(term in combined for term in self.CRIMINAL_TERMS)

    def _query_api(self, keyword: str, year: int) -> list[str]:
        payload = {
            'PKYWRD': keyword,
            'PCSEKWYR': str(year),
            'PAFR': '9999',
            'PISSWS': '0'
        }
        r = self.session.post(self.search_url, json=payload, verify=False, timeout=25)
        collected = []
        if r.status_code == 200:
            data = r.json()
            d_obj = data.get('d')
            if isinstance(d_obj, str):
                records = json.loads(d_obj)
                if isinstance(records, list):
                    for rec in records:
                        if not self._is_criminal_record(rec):
                            continue
                        attach = rec.get('ATTACHMENTS')
                        if attach and isinstance(attach, str) and attach.strip():
                            abs_url = urljoin("https://mis.ihc.gov.pk/", attach.strip())
                            collected.append(abs_url)

        self.logger.info("  IHC API keyword=%r, year=%d returned %d criminal PDF links", keyword, year, len(collected))
        return collected

    def submit_search(self, page, keyword: str):
        pass

    def extract_pdf_links(self, page) -> list[str]:
        return []

    def go_to_next_page(self, page) -> bool:
        return False

    def _url_to_filename(self, url: str) -> str:
        basename = url.split("/")[-1]
        safe_name = re.sub(r"[^\w\.-]", "_", basename)
        return f"{self.year}_IHC_{safe_name}"

    async def _download_pdf(self, url: str) -> Optional[Path]:
        filename = self._url_to_filename(url)
        dest = self.downloads_dir / filename

        # Verify existing file is a valid non-empty PDF
        if dest.exists() and dest.stat().st_size > 0:
            try:
                with open(dest, "rb") as f:
                    if f.read(4) == b"%PDF":
                        self.logger.debug("Skipping already-downloaded valid PDF: %s", filename)
                        return dest
            except Exception:
                pass
            dest.unlink(missing_ok=True)

        # URL encode path to handle spaces and special characters like &, (, )
        encoded_url = urllib.parse.quote(url, safe=":/")
        self.logger.info("Downloading %s ...", filename)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                r = requests.get(encoded_url, headers=headers, verify=False, timeout=25)
                if r.status_code == 200 and len(r.content) > 0 and r.content.startswith(b"%PDF"):
                    with open(dest, "wb") as f:
                        f.write(r.content)
                    self.logger.info("Saved -> %s (%d KB)", filename, len(r.content) // 1024)
                    return dest
                else:
                    self.logger.warning("Attempt %d/%d failed for %s (status=%s, magic_pdf=%s)", attempt, self.max_retries, filename, r.status_code, r.content.startswith(b"%PDF"))
            except Exception as exc:
                self.logger.warning("Attempt %d/%d failed for %s: %s", attempt, self.max_retries, filename, exc)
            await asyncio.sleep(self.retry_delay)

        self.logger.error("All download attempts failed for %s", filename)
        return None
