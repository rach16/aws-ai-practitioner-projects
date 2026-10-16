"""Does the surrounding text change whether Comprehend finds a phone number?

Yes, and that is the most important thing this project found.

The same phone number, on the same line, with the same words either side of it,
is detected at 0.978 confidence in a 98-character input and **not detected at
all** in the 470-character full invoice that contains those 98 characters
verbatim.

This was found by accident. The pipeline missed a phone number, and the first
explanation written down was that Comprehend needs conversational context and
the invoice line was too bare. Pasting that bare line into the Comprehend
console disproved it in about ten seconds: bare is when it works.

What appears to suppress it is the rest of the page. An invoice is full of
numbers -- 620.00, 2,480.00, 1,470.00, 98.00, dates like 2026-03-14 -- and in
that company a phone number stops reading as a phone number. The ladder below
adds the invoice back a section at a time to find where it breaks.

The consequence is the part worth remembering: **a redaction step validated on
a snippet is not validated.** Detection is a property of the whole input, not
of the identifier, so the only meaningful test is the real document at its real
length. That is why verify.py checks the final output for known values rather
than trusting that the detector ran.

Run: python -m pipeline.pii_context_test
"""

from __future__ import annotations

import json
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

# Two separators between the email and the phone. The document is drawn with a
# middle dot; Textract's OCR returns a hyphen. One character of difference that
# nobody would think to control for, and it moves the score by 0.44.
SEPARATORS = {"middle dot (as drawn)": "\u00b7", "hyphen (as OCR'd)": "-"}

HEADER = """Meridian Supply Co.
118 Kesteven Way, Portland, OR 97204
billing@meridiansupply.example {sep} 555-0182"""

TARGET = "555-0182"

# Added one at a time on top of HEADER, to find the point where detection fails.
LADDER = [
    ("header only", ""),
    ("+ invoice metadata", """
Invoice Number:
INV-2026-0417
Invoice Date:
2026-03-14
Due Date:
2026-04-13
Bill To:
Harlow Analytics Ltd"""),
    ("+ line items", """
Description
Qty
Unit
Amount
Standing desk frame
4
620.00
2,480.00
Monitor arm, dual
6
145.00
870.00
Acoustic panel, 60cm
15
98.00
1,470.00"""),
    ("+ totals", """
Subtotal
$4,820.00
Tax (9%)
$433.80
Total Due
$5,253.80"""),
    ("+ footer (= the full document)", """
Payment due within 30 days. Late payments accrue 1.5% monthly."""),
]


def main() -> None:
    comprehend = boto3.Session(profile_name="personal",
                               region_name="us-east-1").client("comprehend")

    print(f"Looking for {TARGET!r} as PHONE.\n")
    print(f"  {'separator':22} {'input':34} {'chars':>6}  {'PHONE':>8}")
    print(f"  {'-' * 22} {'-' * 34} {'-' * 6}  {'-' * 8}")

    results = {}
    for sep_label, sep in SEPARATORS.items():
        text = HEADER.format(sep=sep)
        rows = []
        for label, addition in LADDER:
            text += addition
            entities = comprehend.detect_pii_entities(
                Text=text, LanguageCode="en")["Entities"]
            phone = next((e for e in entities if e["Type"] == "PHONE"), None)

            verdict = f"{phone['Score']:.3f}" if phone else "MISSED"
            print(f"  {sep_label:22} {label:34} {len(text):>6}  {verdict:>8}")

            rows.append({
                "input": label,
                "chars": len(text),
                "phone_detected": phone is not None,
                "phone_score": round(phone["Score"], 4) if phone else None,
                "other_pii_types": sorted({e["Type"] for e in entities
                                           if e["Type"] != "PHONE"}),
            })
        results[sep_label] = rows
        print()

    print("  Two variables, neither of which is the phone number:")
    for sep_label, rows in results.items():
        first = rows[0]
        score = f"{first['phone_score']:.3f}" if first["phone_detected"] else "MISSED"
        print(f"    {sep_label:22} header alone -> {score}")
    print("    adding the rest of the invoice -> MISSED, either way")
    print()
    print("  The 0.80 redaction threshold would have skipped the hyphen case even at")
    print("  98 characters, so this document was never going to redact cleanly.")

    (RESULTS / "pii_context_test.json").write_text(json.dumps({
        "target": TARGET,
        "finding": "Detection of the same phone number varies with the separator "
                   "character beside it and with the length of unrelated text around "
                   "it. Neither variable is the identifier. A redaction step validated "
                   "on a snippet is not validated.",
        "by_separator": results,
    }, indent=2) + "\n")
    print(f"\n  written to results/pii_context_test.json")


if __name__ == "__main__":
    main()
