"""Fetch per-token prices for the model lineup from the AWS Pricing API.

Bedrock on-demand inference is billed per 1,000 tokens, at a different rate for
input and output. Those rates are published through the Pricing API, which only
answers in us-east-1 regardless of which region you are pricing.

Two things make this less tidy than it sounds, and both are handled here rather
than papered over:

1. A model's pricing record is keyed by `usagetype`, which does not match its
   `modelId`. `amazon.nova-micro-v1:0` is priced under `USE1-NovaMicro-*`. So
   config/models.json carries the usagetype prefix explicitly and we match on it
   exactly, which also keeps the cheaper `-flex`, the dearer `-priority` and the
   prompt-cache rates from being picked up by accident.

2. Some models are not in the Pricing API at all. Every current Anthropic model
   is missing from us-east-1; only the legacy Claude 2.x and Claude 3 entries are
   published. Those models carry a `price_override` in config, hand-copied from
   the public pricing page with a date, and the report marks them so a fetched
   number is never confused with a typed one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import boto3

CONFIG = Path(__file__).resolve().parent.parent / "config"
MODELS_FILE = CONFIG / "models.json"
PRICING_FILE = CONFIG / "pricing.json"

# The Pricing API is only served from these two regions.
PRICING_REGION = "us-east-1"


def load_models() -> dict:
    return json.loads(MODELS_FILE.read_text())


def fetch_catalogue(session: boto3.Session, region: str) -> dict[str, dict]:
    """Return {usagetype: {usd_per_1k, unit, published}} for Bedrock in `region`."""
    client = session.client("pricing", region_name=PRICING_REGION)
    paginator = client.get_paginator("get_products")
    catalogue: dict[str, dict] = {}

    for page in paginator.paginate(
        ServiceCode="AmazonBedrock",
        Filters=[{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region}],
    ):
        for blob in page["PriceList"]:
            record = json.loads(blob)
            usagetype = record["product"]["attributes"].get("usagetype")
            if not usagetype:
                continue
            for term in record["terms"].get("OnDemand", {}).values():
                for dimension in term["priceDimensions"].values():
                    catalogue[usagetype] = {
                        "usd_per_1k": float(dimension["pricePerUnit"]["USD"]),
                        "unit": dimension["unit"],
                        "published": record.get("publicationDate"),
                    }
    return catalogue


def resolve(models: dict, catalogue: dict[str, dict]) -> dict:
    """Attach an input and output rate to every model in the lineup."""
    resolved = {}
    for model in models["models"]:
        key = model["key"]
        override = model.get("price_override")

        if override:
            resolved[key] = {
                "input_usd_per_1k": override["input_usd_per_1k"],
                "output_usd_per_1k": override["output_usd_per_1k"],
                "source": "manual",
                "source_detail": override["source"],
                "checked": override["checked"],
            }
            continue

        prefix = model.get("price_match")
        rates = {}
        for side in ("input", "output"):
            entry = catalogue.get(f"{prefix}-{side}-tokens")
            if entry is None:
                rates = {}
                break
            rates[f"{side}_usd_per_1k"] = entry["usd_per_1k"]

        if not rates:
            resolved[key] = {
                "input_usd_per_1k": None,
                "output_usd_per_1k": None,
                "source": "unavailable",
                "source_detail": f"No usagetype {prefix}-input-tokens / -output-tokens in the Pricing API",
            }
            continue

        resolved[key] = {
            **rates,
            "source": "pricing-api",
            "source_detail": f"{prefix}-input-tokens / {prefix}-output-tokens",
        }
    return resolved


def main() -> None:
    models = load_models()
    region = models["region"]
    session = boto3.Session(profile_name="personal", region_name=region)

    catalogue = fetch_catalogue(session, region)
    resolved = resolve(models, catalogue)

    payload = {
        "region": region,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalogue_size": len(catalogue),
        "prices": resolved,
    }
    PRICING_FILE.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"{len(catalogue)} Bedrock pricing records in {region}\n")
    for key, price in resolved.items():
        if price["source"] == "unavailable":
            print(f"  {key:20} NO PRICE  {price['source_detail']}")
            continue
        flag = "manual" if price["source"] == "manual" else "api"
        print(
            f"  {key:20} in ${price['input_usd_per_1k'] * 1000:>7.2f}/1M   "
            f"out ${price['output_usd_per_1k'] * 1000:>7.2f}/1M   [{flag}]"
        )
    print(f"\nwritten to {PRICING_FILE.relative_to(Path.cwd()) if PRICING_FILE.is_relative_to(Path.cwd()) else PRICING_FILE}")


if __name__ == "__main__":
    main()
