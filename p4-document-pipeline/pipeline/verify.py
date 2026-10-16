"""Fail if any known identifier survived redaction.

This exists because the first version of the pipeline produced output with a
live phone number in it and every check passed. The checks confirmed that the
pipeline ran, which is not the same question as whether it worked.

The gate is only possible because the documents are synthetic: the exact
strings that must not appear are already written down in ground_truth.json. On
real documents you cannot write this test, which is a good argument for
building the pipeline against synthetic data first and an uncomfortable fact
about redaction in general.

Run before committing. Exits non-zero on a leak so it can be wired into CI or
a pre-commit hook.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
RESULTS = ROOT / "results"

# Field names whose values are personal and must never survive into redacted
# output. Anything not listed here is business data: an invoice total is not
# PII and redacting it would make the pipeline useless.
SENSITIVE_FIELDS = {
    "ssn", "contact_email", "contact_phone", "employee_name",
    "sender_name", "recipient_name",
}


def main() -> None:
    truth = json.loads((DOCS / "ground_truth.json").read_text())
    comprehend = json.loads((RESULTS / "comprehend.json").read_text())

    leaks = []
    checked = 0

    for name, doc in truth.items():
        redacted = comprehend[name]["redacted_text"]
        for field, value in doc["fields"].items():
            if field not in SENSITIVE_FIELDS:
                continue
            checked += 1
            if str(value) in redacted:
                leaks.append((name, field, value))

    for name, field, value in leaks:
        print(f"  LEAK  {name}.{field} = {value!r} survived redaction")

    if leaks:
        print(f"\n{len(leaks)} of {checked} sensitive values leaked. Do not commit this output.")
        sys.exit(1)

    print(f"  {checked} sensitive values checked across {len(truth)} documents, none survived")

    below = [(name, s) for name, doc in comprehend.items()
             for s in doc["pii_skipped_below_threshold"]]
    if below:
        print(f"  {len(below)} low-confidence PII hit(s) left unredacted for review:")
        textract = json.loads((RESULTS / "textract.json").read_text())
        for name, skipped in below:
            raw = textract[name]["text"][skipped["span"][0]:skipped["span"][1]]
            print(f"      {name}: {skipped['type']} {raw!r} at {skipped['score']}")

    backstopped = [(name, c) for name, doc in comprehend.items()
                   for c in doc["backstop_caught"]]
    if backstopped:
        print(f"  {len(backstopped)} value(s) caught only by the regex backstop, "
              f"not by Comprehend:")
        for name, caught in backstopped:
            print(f"      {name}: {caught['type']}")


if __name__ == "__main__":
    main()
