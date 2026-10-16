"""Fetch what this pipeline costs per page, per document and per million.

Textract prices come from the AWS Pricing API. Comprehend's do not: the API
returns zero records for AmazonComprehend in us-east-1, so its rate is entered
by hand with the date and the source, and flagged in the output. This is the
same situation P1 hit with Anthropic, and gets the same treatment, because a
typed number mixed silently into fetched ones makes the whole table look
machine-verified when it is not.

The Textract catalogue is worth reading rather than skimming. The feature types
are priced **per combination**, not added up, and the combinations differ by
nearly fifty times:

    SyncTextPagesProcessed                 $0.0015   raw OCR only
    SyncQueriesPagesProcessed              $0.015    queries only
    SyncFormsQueriesTablesPagesProcessed   $0.07     all three, what we ran

So asking for FORMS and TABLES alongside QUERIES, which the first version of
extract.py did on the grounds that one call is cheaper than three, cost 4.7x
what QUERIES alone would have. One call is cheaper than three calls for the
same features; it is not cheaper than asking for only what you use.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

# The exact usagetypes this pipeline could bill against, and what each buys.
TEXTRACT_USAGE = {
    "ocr_only": ("USE1-SyncTextPagesProcessed", "DetectDocumentText: raw text, no structure"),
    "queries_only": ("USE1-SyncQueriesPagesProcessed", "AnalyzeDocument with QUERIES alone"),
    "queries_tables": ("USE1-SyncQueriesTablesPagesProcessed", "QUERIES + TABLES"),
    "forms_only": ("USE1-SyncFormsPagesProcessed", "FORMS alone"),
    "all_three": ("USE1-SyncFormsQueriesTablesPagesProcessed", "FORMS + TABLES + QUERIES"),
    "async_all_three": ("USE1-AsyncFormsQueriesTablesPagesProcessed", "Same, via S3"),
}

COMPREHEND_MANUAL = {
    "usd_per_unit": 0.0001,
    "chars_per_unit": 100,
    "minimum_units_per_request": 3,
    "source": "https://aws.amazon.com/comprehend/pricing/ (first 10M units tier)",
    "checked": "2026-10-16",
    "reason": "The AWS Pricing API returns no records for AmazonComprehend in "
              "us-east-1, so this rate is hand-entered and flagged rather than "
              "fetched. Each API call bills a 300-character minimum, so four "
              "calls against one short document cost more than one call against "
              "a document four times the length.",
}


def fetch_textract(session) -> dict:
    client = session.client("pricing", region_name="us-east-1")
    catalogue = {}
    for page in client.get_paginator("get_products").paginate(
        ServiceCode="AmazonTextract",
        Filters=[{"Type": "TERM_MATCH", "Field": "regionCode", "Value": "us-east-1"}],
    ):
        for blob in page["PriceList"]:
            record = json.loads(blob)
            usagetype = record["product"]["attributes"].get("usagetype")
            for term in record["terms"].get("OnDemand", {}).values():
                for dimension in term["priceDimensions"].values():
                    # Only the first pricing tier; volume discounts start at 1M pages.
                    if dimension.get("beginRange") not in ("0", None):
                        continue
                    catalogue[usagetype] = float(dimension["pricePerUnit"]["USD"])

    resolved = {}
    for key, (usagetype, description) in TEXTRACT_USAGE.items():
        rate = catalogue.get(usagetype)
        resolved[key] = {
            "usd_per_page": rate,
            "usagetype": usagetype,
            "description": description,
            "source": "pricing-api" if rate is not None else "unavailable",
        }
    return resolved


def main() -> None:
    session = boto3.Session(profile_name="personal", region_name="us-east-1")
    textract = fetch_textract(session)

    payload = {
        "region": "us-east-1",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "textract": textract,
        "comprehend": {**COMPREHEND_MANUAL, "source_type": "manual"},
    }
    CONFIG.mkdir(exist_ok=True)
    (CONFIG / "pricing.json").write_text(json.dumps(payload, indent=2) + "\n")

    print("Textract, per page, us-east-1, first tier:\n")
    for key, entry in sorted(textract.items(), key=lambda kv: kv[1]["usd_per_page"] or 0):
        rate = entry["usd_per_page"]
        print(f"  {key:18} ${rate:<9.4f} {entry['description']}")

    cheapest = min(v["usd_per_page"] for v in textract.values() if v["usd_per_page"])
    dearest = max(v["usd_per_page"] for v in textract.values() if v["usd_per_page"])
    print(f"\n  spread: {dearest / cheapest:.0f}x between the cheapest and dearest option")
    print(f"\nComprehend: ${COMPREHEND_MANUAL['usd_per_unit']} per "
          f"{COMPREHEND_MANUAL['chars_per_unit']}-char unit, "
          f"{COMPREHEND_MANUAL['minimum_units_per_request']}-unit minimum  [manual]")
    print("\nwritten to config/pricing.json")


if __name__ == "__main__":
    main()
