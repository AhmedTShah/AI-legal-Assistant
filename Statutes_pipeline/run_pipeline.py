"""
run_pipeline.py
================
Master execution script for the LawMind Statutes Pipeline.
Coordinates collection creation, PDF parsing, and Qdrant database ingestion.
"""

import sys
import argparse
from pathlib import Path

# Configure terminal encoding to prevent UnicodeEncodeError on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add Statutes_pipeline directory and parent directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parent.parent))

def main():
    ap = argparse.ArgumentParser(
        description="LawMind Master Pipeline Runner"
    )
    ap.add_argument("--dry-run",     action="store_true",
                    help="Parse only and test embeddings, skip Qdrant upsert")
    ap.add_argument("--type",        choices=["acts_ordinances", "rules_orders", "notifications_sro", "schedule_tables"],
                    help="Process only this subcategory")
    ap.add_argument("--import-json", type=str, metavar="FILE",
                    help="Ingest pre-parsed chunks from JSON instead of parsing PDFs")
    args = ap.parse_args()

    print("=" * 62)
    print("  STARTING LAWMIND FULL PIPELINE")
    print("=" * 62)

    # 1. Create/Verify Collection (create_statute_coll.py)
    if not args.dry_run:
        print("\n[Step 1/2] Creating/Verifying Qdrant Collection...")
        try:
            # Import to trigger the collection creation script
            import create_statute_coll
        except Exception as e:
            # If it fails because the collection already exists, ignore and continue
            if "already exists" in str(e).lower():
                print("[INFO] Collection already exists. Proceeding...")
            else:
                print(f"[ERROR] Error during collection creation: {e}")
                sys.exit(1)
    else:
        print("\n[Step 1/2] Dry-run active: skipping collection check/creation.")

    # 2. Parse PDFs and Ingest to Qdrant (qdrant_ingest.py)
    if args.import_json:
        print("\n[Step 2/2] Loading pre-parsed JSON and Ingesting to Qdrant...")
    else:
        print("\n[Step 2/2] Parsing PDFs and Ingesting to Qdrant...")
    try:
        import qdrant_ingest
        # Run the ingestion script
        qdrant_ingest.run(
            dry_run=args.dry_run,
            subcat_filter=args.type,
            import_json_path=args.import_json
        )
    except Exception as e:
        print(f"[ERROR] Error during parsing/ingestion: {e}")
        sys.exit(1)

    print("\n" + "=" * 62)
    print("  PIPELINE EXECUTION COMPLETED SUCCESSFULLY!")
    print("=" * 62)

if __name__ == "__main__":
    main()
