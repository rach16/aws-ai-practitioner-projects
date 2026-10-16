"""Score all three approaches against the ground truth, on the same terms.

The scoring has to normalise before comparing, or it measures formatting. Both
of these are the same date and the same amount:

    2026-01-22   vs   22 January 2026
    5253.8       vs   $5,253.80

Marking either pair as a mismatch would say Textract is wrong about a date it
read perfectly. So money is reduced to a number, dates to ISO, and free text is
lowercased with punctuation stripped. Every approach gets the identical
treatment, which is the only thing that makes the comparison worth anything.

The distinction that matters most here is between **wrong** and **absent**.
Textract returns nothing when it cannot find a field. A prompted model returns
something for every field it is asked about, because that is what the
instruction asks of it, and "nothing found" is a harder answer for a model to
give than a plausible one. Those two failure modes are not equivalent, and a
single accuracy figure hides the difference, so they are counted separately:

    correct     the right value
    wrong       a value, but the wrong one   <- costs you silently
    missing     no value offered             <- you know to go and look
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
RESULTS = ROOT / "results"

MONEY_FIELDS = re.compile(r"(_usd|amount|total|subtotal|tax|pay)$")
DATE_FIELDS = re.compile(r"(date|_end|ending)$")

DATE_FORMATS = (
    "%Y-%m-%d", "%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y",
    "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
)


def as_money(value) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def as_date(value) -> str | None:
    if value is None:
        return None
    text = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", str(value).strip(), flags=re.I)
    text = text.replace(",", "")
    # Trailing time, as in "9 February 2026 at 10:30", is not part of the date.
    text = re.split(r"\s+at\s+", text, flags=re.I)[0].strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def as_text(value) -> str | None:
    if value is None:
        return None
    return " ".join(re.sub(r"[^\w\s@.\-]", " ", str(value).lower()).split()).strip(" .")


def compare(field: str, expected, actual) -> str:
    """One of: correct, wrong, missing."""
    if actual is None or str(actual).strip() in ("", "null", "None", "N/A"):
        return "missing"

    if MONEY_FIELDS.search(field):
        want, got = as_money(expected), as_money(actual)
        return "correct" if want is not None and want == got else "wrong"

    if DATE_FIELDS.search(field):
        want, got = as_date(expected), as_date(actual)
        return "correct" if want is not None and want == got else "wrong"

    want, got = as_text(expected), as_text(actual)
    if want == got:
        return "correct"
    # A value that contains the expected string and little else is the same
    # answer with a title or honorific attached, not a different answer.
    if want and got and want in got and len(got) <= len(want) + 6:
        return "correct"
    return "wrong"


def tally(results: dict[str, str]) -> dict[str, int]:
    counts = {"correct": 0, "wrong": 0, "missing": 0}
    for verdict in results.values():
        counts[verdict] += 1
    return counts


def main() -> None:
    truth = json.loads((DOCS / "ground_truth.json").read_text())
    textract = json.loads((RESULTS / "textract.json").read_text())
    llm = json.loads((RESULTS / "llm.json").read_text())

    approaches: dict[str, dict[str, dict[str, str]]] = {}

    # Textract Queries
    approaches["textract-queries"] = {}
    for doc, spec in truth.items():
        answers = textract[doc]["queries"]
        approaches["textract-queries"][doc] = {
            field: compare(field, expected, answers.get(field, {}).get("answer"))
            for field, expected in spec["fields"].items()
        }

    # Each model
    for model, docs in llm.items():
        approaches[model] = {}
        for doc, spec in truth.items():
            fields = (docs.get(doc) or {}).get("fields") or {}
            approaches[model][doc] = {
                field: compare(field, expected, fields.get(field))
                for field, expected in spec["fields"].items()
            }

    summary = {}
    for approach, docs in approaches.items():
        flat = {f"{doc}.{field}": verdict
                for doc, fields in docs.items() for field, verdict in fields.items()}
        summary[approach] = {
            "per_field": flat,
            "totals": tally(flat),
            "per_document": {doc: tally(fields) for doc, fields in docs.items()},
        }

    (RESULTS / "scores.json").write_text(json.dumps(summary, indent=2) + "\n")

    total = len(next(iter(summary.values()))["per_field"])
    print(f"{total} fields across {len(truth)} documents\n")
    print(f"  {'approach':20} {'correct':>8} {'wrong':>7} {'missing':>8}")
    for approach, data in summary.items():
        t = data["totals"]
        print(f"  {approach:20} {t['correct']:>8} {t['wrong']:>7} {t['missing']:>8}")

    print("\ndisagreements:")
    fields = list(next(iter(summary.values()))["per_field"])
    for field in fields:
        verdicts = {a: summary[a]["per_field"][field] for a in summary}
        if len(set(verdicts.values())) > 1:
            print(f"  {field:28} " + "  ".join(f"{a}={v}" for a, v in verdicts.items()))

    print("\nwritten to results/scores.json")


if __name__ == "__main__":
    main()
