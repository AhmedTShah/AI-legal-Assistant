"""
run_all.py — Entry point to run all court scrapers concurrently.

Usage:
    python -m scraper.run_all --keyword "PECA" --pages 5
    python -m scraper.run_all --keyword "cybercrime" --courts lhc shc
"""

import argparse
import asyncio
import logging
from pathlib import Path

from scraper.courts.lhc import LHCScraper
from scraper.courts.shc import SHCScraper
from scraper.courts.ihc import IHCScraper
from scraper.courts.scp import SCPScraper
from scraper.courts.phc import PHCScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_all")

COURT_REGISTRY = {
    "lhc": LHCScraper,
    "shc": SHCScraper,
    "ihc": IHCScraper,
    "scp": SCPScraper,
    "phc": PHCScraper,
}


async def run_scraper_safe(name, scraper_cls, keyword, pages, downloads_dir):
    """Run a single scraper and catch NotImplementedError for stubs."""
    try:
        scraper = scraper_cls(keyword=keyword, max_pages=pages, downloads_dir=downloads_dir)
        results = await scraper.run()
        logger.info("[%s] %d PDF(s) downloaded.", name.upper(), len(results))
        return name, results
    except NotImplementedError:
        logger.warning("[%s] Scraper is a stub — skipping.", name.upper())
        return name, []
    except Exception as exc:
        logger.error("[%s] Failed: %s", name.upper(), exc, exc_info=True)
        return name, []


async def main(keyword, courts, pages, downloads_dir):
    tasks = [
        run_scraper_safe(
            name=court,
            scraper_cls=COURT_REGISTRY[court],
            keyword=keyword,
            pages=pages,
            downloads_dir=downloads_dir,
        )
        for court in courts
        if court in COURT_REGISTRY
    ]

    results = await asyncio.gather(*tasks)
    total = sum(len(pdfs) for _, pdfs in results)

    print(f"\n{'='*55}")
    print(f"  Run complete — {total} PDF(s) downloaded across {len(results)} court(s)")
    print(f"{'='*55}")
    for court, pdfs in results:
        status = f"{len(pdfs)} PDF(s)" if pdfs else "0 / skipped"
        print(f"  {court.upper():>5} : {status}")


def parse_args():
    parser = argparse.ArgumentParser(description="Run all (or selected) court scrapers.")
    parser.add_argument("--keyword", default="PECA")
    parser.add_argument(
        "--courts", nargs="+", default=list(COURT_REGISTRY.keys()),
        choices=list(COURT_REGISTRY.keys()),
    )
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument(
        "--downloads-dir", type=Path,
        default=Path(__file__).parent.parent / "downloads",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.keyword, args.courts, args.pages, args.downloads_dir))
