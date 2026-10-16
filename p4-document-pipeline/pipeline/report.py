"""Put accuracy and cost in the same table, because neither means much alone.

Model token prices are read from P1's config/pricing.json rather than
re-fetched. P1 already solved that problem, the rates are the same account and
region, and a second copy would be a second thing to go stale.

Costs are projected to 1,000 documents. At three documents every option here
costs a fraction of a cent and they all look free, which is the same reason
P1 projects to 10,000 requests.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
CONFIG = ROOT / "config"
RESULTS = ROOT / "results"
DOCS = ROOT / "docs"

PROJECTION = 1_000


def comprehend_cost(texts: list[str], price: dict, calls_per_doc: int = 4) -> float:
    """Comprehend bills per 100-char unit with a 300-char minimum, per call."""
    total = 0.0
    for text in texts:
        units = max(price["minimum_units_per_request"],
                    -(-len(text) // price["chars_per_unit"]))
        total += units * price["usd_per_unit"] * calls_per_doc
    return total


def main() -> None:
    truth = json.loads((DOCS / "ground_truth.json").read_text())
    textract = json.loads((RESULTS / "textract.json").read_text())
    llm = json.loads((RESULTS / "llm.json").read_text())
    scores = json.loads((RESULTS / "scores.json").read_text())
    price = json.loads((CONFIG / "pricing.json").read_text())
    model_price = json.loads((REPO / "p1-model-bench" / "config" / "pricing.json").read_text())["prices"]

    n_docs = len(truth)
    texts = [doc["text"] for doc in textract.values()]
    per_doc = lambda total: total / n_docs

    # Comprehend runs in every option: redaction is required regardless of who
    # does the extraction, and it is the only one of the three that returns
    # character offsets to redact by.
    comp_per_doc = per_doc(comprehend_cost(texts, price["comprehend"]))

    rows = []

    tq = price["textract"]["queries_only"]["usd_per_page"]
    rows.append({
        "approach": "textract-queries",
        "label": "Textract QUERIES, then Comprehend",
        "extract_per_doc": tq,
        "scores": scores["textract-queries"]["totals"],
        "note": "Deterministic. Confidence per field.",
    })

    all3 = price["textract"]["all_three"]["usd_per_page"]
    rows.append({
        "approach": "textract-all-features",
        "label": "Textract FORMS+TABLES+QUERIES (what was actually run)",
        "extract_per_doc": all3,
        "scores": scores["textract-queries"]["totals"],
        "note": "Same answers as the row above. FORMS and TABLES went unused.",
    })

    ocr = price["textract"]["ocr_only"]["usd_per_page"]
    for model in llm:
        rate = model_price[model]
        tokens_in = sum(d["input_tokens"] for d in llm[model].values() if "input_tokens" in d)
        tokens_out = sum(d["output_tokens"] for d in llm[model].values() if "output_tokens" in d)
        model_cost = per_doc((tokens_in / 1000) * rate["input_usd_per_1k"]
                             + (tokens_out / 1000) * rate["output_usd_per_1k"])
        rows.append({
            "approach": f"ocr+{model}",
            "label": f"Textract OCR only, then {model}",
            "extract_per_doc": ocr + model_cost,
            "scores": scores[model]["totals"],
            "note": f"No confidence scores. Price source for the model: {rate['source']}.",
            "tokens": (tokens_in, tokens_out),
        })

    lines: list[str] = []
    add = lines.append

    add("# Document pipeline results\n")
    add(f"{n_docs} synthetic documents, "
        f"{len(scores['textract-queries']['per_field'])} fields with known correct answers, "
        f"us-east-1. Prices fetched {price['fetched_at']}.\n")

    add("\n## Accuracy and cost\n")
    add("| Approach | Correct | Wrong | Missing | Extract /1k | + Comprehend | Total /1k |")
    add("|---|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        s = row["scores"]
        extract = row["extract_per_doc"] * PROJECTION
        comp = comp_per_doc * PROJECTION
        add(f"| {row['label']} | {s['correct']} | {s['wrong']} | {s['missing']} "
            f"| ${extract:,.2f} | ${comp:,.2f} | **${extract + comp:,.2f}** |")

    add("\n`Comprehend` is the same in every row: PII detection and redaction are needed "
        "whoever does the extraction, and it is the only one of the three that returns "
        "character offsets to redact by.\n")

    add("\n## Where they disagree\n")
    fields = list(scores["textract-queries"]["per_field"])
    disagreements = [f for f in fields
                     if len({scores[a]["per_field"][f] for a in scores}) > 1]
    add(f"{len(disagreements)} of {len(fields)} fields. On the other "
        f"{len(fields) - len(disagreements)} every approach agreed.\n")
    add("| Field | Textract | " + " | ".join(m for m in llm) + " | Why |")
    add("|---|---|" + "---|" * (len(llm) + 1))

    why = {
        "invoice.tax_usd": "Label reads `Tax (9%)`. Textract returned `(9%)` at 79% confidence.",
        "invoice.contact_phone": "Bare number on a letterhead line, no label to attach it to.",
        "paystub.employer_name": "It is the letterhead. No field labels it as the employer.",
        "letter.appointment_date": "Buried in prose: *see you again on 9 February 2026 at 10:30*.",
    }
    for field in disagreements:
        cells = " | ".join(scores[a]["per_field"][field] for a in scores)
        add(f"| `{field}` | {cells} | {why.get(field, '')} |")

    add("\nEvery disagreement is a field with **no label on the page**. That is the dividing "
        "line: Textract Queries needs something to anchor to, and a language model does not.\n")

    add("\n## What the models were not asked to do\n")
    add("Both models returned a value for all "
        f"{len(scores['textract-queries']['per_field'])} fields and used `null` zero times, "
        "though the instruction offered it and said not to guess. Here every one of those "
        "values was correct, so the difference between confident knowledge and confident "
        "invention never showed up.\n")
    add("That is the risk the accuracy column cannot measure. Textract's three `missing` "
        "answers are a worse score and a better failure: a missing field routes itself to a "
        "human, and a wrong field does not announce anything. Add a confidence score to that "
        "and Textract can route only the uncertain ones, which is the behaviour you want in "
        "production and the thing the model does not offer.\n")

    add("\n## Cost notes\n")
    add("**The feature combination is the cost decision, not the call count.** Textract "
        "prices feature combinations rather than adding features up:\n")
    add("| Call | Per page |")
    add("|---|---:|")
    for key, entry in sorted(price["textract"].items(), key=lambda kv: kv[1]["usd_per_page"] or 0):
        add(f"| {entry['description']} | ${entry['usd_per_page']:.4f} |")
    add("")
    add("The first version of `extract.py` asked for FORMS, TABLES and QUERIES in one call, "
        "reasoning that one call beats three. One call does beat three calls for the same "
        "features. It does not beat asking only for what you use, and here FORMS and TABLES "
        "were never read: **$0.07 a page instead of $0.015, for identical answers.**\n")
    add("Comprehend's rate is hand-entered. The AWS Pricing API returns no records for "
        f"AmazonComprehend in us-east-1, so ${price['comprehend']['usd_per_unit']} per "
        f"{price['comprehend']['chars_per_unit']}-character unit comes from "
        f"{price['comprehend']['source']}, checked {price['comprehend']['checked']}. "
        "Its 300-character minimum per request means four calls against a short document "
        "cost more than one call against a document four times longer.\n")

    (RESULTS / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:22]))
    print(f"\n... written to results/REPORT.md")


if __name__ == "__main__":
    main()
