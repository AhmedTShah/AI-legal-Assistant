import re
import math
import time
from urllib.parse import quote, urlparse, parse_qs
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Filter Target Lists
MINISTRIES = [
    "Law and Justice",
    "Information Technology and Telecommunication",
    "Interior",
    "Human Rights",
]

SUBCATEGORIES = [
    "Act",
    "Ordinance",
    "Rules",
    "Notification",
    "Order",
]

LAW_CATEGORIES = [
    "Cyber Laws",
    "Criminal Laws",
    "Civil and Court Procedure",
    "Procedural Law",
    "Police Laws",
    "Witness Protection Law",
    "National Counter Terrorism Authority Law",
    "Anti-Corruption Law",
    "Digital Transformation",
    "Information Technology Laws",
    "Women Laws",
    "Human Right Law",
]


def audit_matrix_document_counts():
    """Audit and count total documents across all filter matrix combinations."""
    print("=" * 80)
    print(" LEGALMIND - MATRIX COMBINATIONS COUNT AUDITOR SUITE")
    print("=" * 80)

    total_combinations = len(MINISTRIES) * len(SUBCATEGORIES) * len(LAW_CATEGORIES)
    print(f" [+] Total Filter Combinations to Audit: {total_combinations}")
    print(" [+] Initializing Headless Browser Auditor...\n")

    unique_doc_keys = set()
    combination_results = []
    combo_counter = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for ministry in MINISTRIES:
            for subcat in SUBCATEGORIES:
                for lawcat in LAW_CATEGORIES:
                    combo_counter += 1
                    encoded_m = quote(ministry)
                    encoded_sub = quote(subcat)
                    encoded_law = quote(lawcat)

                    # Query Page 1 to inspect total reported count
                    url = (
                        f"https://drs.molaw.gov.pk/documents?"
                        f"ministry={encoded_m}&"
                        f"subCategory={encoded_sub}&"
                        f"lawCategory={encoded_law}&"
                        f"pageNumber=1&"
                        f"pageSize=50"
                    )

                    try:
                        page.goto(url, wait_until="networkidle", timeout=45000)
                        page.wait_for_selector("body", timeout=10000)
                        html_content = page.content()
                        soup = BeautifulSoup(html_content, "html.parser")

                        showing_text = soup.get_text()
                        count_match = re.search(r"Showing\s+\d+\s+of\s+(\d+)", showing_text, re.IGNORECASE)

                        found_count = 0
                        if count_match:
                            found_count = int(count_match.group(1))

                        # Extract document version links to record unique keys
                        links = soup.find_all("a", href=True)
                        combo_unique_keys = set()

                        for link in links:
                            href = link["href"]
                            if "docId=" in href or "document-versions" in href:
                                query_params = parse_qs(urlparse(href).query)
                                doc_id = query_params.get("docId", [""])[0]
                                version_id = query_params.get("versionId", [""])[0]

                                if doc_id:
                                    comp_key = f"{doc_id}_{version_id}" if version_id else doc_id
                                    unique_doc_keys.add(comp_key)
                                    combo_unique_keys.add(comp_key)

                        combination_results.append({
                            "combo_num": combo_counter,
                            "ministry": ministry,
                            "subcat": subcat,
                            "lawcat": lawcat,
                            "reported_count": found_count,
                            "page1_unique_keys": len(combo_unique_keys)
                        })

                        status_symbol = "✅" if found_count > 0 else "⚪"
                        print(
                            f" [{combo_counter}/{total_combinations}] {status_symbol} "
                            f"Ministry: '{ministry[:20]}' | Subcat: '{subcat}' | LawCat: '{lawcat[:25]}' "
                            f"==> Total Found: {found_count} doc(s)"
                        )

                    except Exception as e:
                        print(f" [{combo_counter}/{total_combinations}] ❌ Error inspecting combo: {e}")

        browser.close()

    # AUDIT SUMMARY
    print("\n" + "=" * 80)
    print(" MATRIX AUDIT COMPLETE - SUMMARY REPORT")
    print("=" * 80)
    print(f" Total Combinations Checked: {total_combinations}")
    active_combos = [c for c in combination_results if c["reported_count"] > 0]
    print(f" Combinations with Results (>0 docs): {len(active_combos)}")
    raw_sum = sum(c["reported_count"] for c in combination_results)
    print(f" Raw Combined Count (Sum of all filters): {raw_sum}")
    print(f" Total UNIQUE Composite Documents (De-duplicated): {len(unique_doc_keys)}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    audit_matrix_document_counts()
