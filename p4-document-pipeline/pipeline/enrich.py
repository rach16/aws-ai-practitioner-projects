"""Comprehend: text to meaning, and the redaction step.

Textract hands over a wall of text. Comprehend is what turns it into something
you can route, file or refuse to store:

  detect_entities       people, organisations, dates, quantities, places
  detect_pii_entities   the subset that is personal, with character offsets
  detect_sentiment      only meaningful on prose, so only the letter gets it
  detect_key_phrases    what the document is about

The PII call is the one that earns its place. It returns character offsets, not
just a list of findings, which is what makes mechanical redaction possible:
walk the spans in reverse and replace each one, and the offsets of the spans
you have not reached yet are still valid. Doing it forwards shifts every
remaining offset and corrupts the output, quietly, in a way that looks fine on
short documents.

Why not ask a foundation model to find the PII instead. Three reasons, and the
third is the one that matters. It is deterministic, so the same document redacts
the same way every time. It returns a confidence per finding, so a borderline
case can be escalated rather than guessed at. And it cannot do the one thing a
generative model can always do, which is quietly rewrite the text it was asked
to redact. A redaction step that occasionally paraphrases is worse than none,
because it looks like it worked.

Billing is per 100-character unit with a 300-character minimum per request, so
a very short document costs the same as a 300-character one. Nothing here is
long enough for that to matter, but it is why batching tiny documents into one
call is worth doing at volume.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

# Below this, a finding is reported but not acted on. Redaction is destructive,
# so a low-confidence hit is surfaced for review rather than silently applied.
REDACT_THRESHOLD = 0.80

# Backstop patterns, applied after Comprehend.
#
# This exists because Comprehend missed a phone number on the invoice while
# finding the identical format in the letter. The first explanation written
# down was that detection needs conversational context and the invoice line
# was too bare; that was wrong, and pii_context_test.py shows why. On those
# three lines alone the number scores 0.978. Adding the rest of the invoice
# drives it to MISSED, and swapping the middle dot beside it for the hyphen
# Textract actually returns costs another 0.44.
#
# So detection is a property of the whole input, not of the identifier, and it
# moves with things nobody would think to control for. A regex is the opposite:
# blind to everything around it, perfect on format. Neither alone is enough for
# a redaction step, where a single miss is the whole failure, so both run and
# the union is redacted. False positives here cost a redacted string that did
# not need it, which is the cheap direction to be wrong in.
BACKSTOP = {
    "PHONE": re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3,4}[-. ]?\d{0,4}\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d{4}[- ]){3}\d{4}\b"),
}


def backstop_spans(text: str, found: list[dict]) -> list[dict]:
    """Pattern matches that Comprehend did not already cover.

    A span is only added when it does not overlap something Comprehend found,
    so a hit both agree on is not redacted twice.
    """
    covered = [(e["BeginOffset"], e["EndOffset"]) for e in found]
    extra = []
    for pii_type, pattern in BACKSTOP.items():
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < c_end and end > c_start for c_start, c_end in covered):
                continue
            extra.append({"Type": pii_type, "Score": 1.0,
                          "BeginOffset": start, "EndOffset": end,
                          "Source": "backstop"})
            covered.append((start, end))
    return extra


def client():
    return boto3.Session(profile_name="personal", region_name="us-east-1").client("comprehend")


def redact(text: str, pii: list[dict], threshold: float = REDACT_THRESHOLD) -> tuple[str, list[dict]]:
    """Replace each confident PII span with [TYPE]. Returns the text and what was skipped.

    Spans are applied in reverse order so that each replacement leaves the
    offsets of the not-yet-processed spans untouched.
    """
    applied, skipped = [], []
    for entity in sorted(pii, key=lambda e: e["BeginOffset"], reverse=True):
        record = {
            "type": entity["Type"],
            "score": round(entity["Score"], 3),
            "span": [entity["BeginOffset"], entity["EndOffset"]],
            "original_length": entity["EndOffset"] - entity["BeginOffset"],
        }
        if entity["Score"] < threshold:
            skipped.append(record)
            continue
        text = text[:entity["BeginOffset"]] + f"[{entity['Type']}]" + text[entity["EndOffset"]:]
        applied.append(record)

    return text, skipped


def analyse(comprehend, text: str, want_sentiment: bool) -> dict:
    language = comprehend.detect_dominant_language(Text=text)["Languages"][0]

    entities = comprehend.detect_entities(Text=text, LanguageCode="en")["Entities"]
    pii = comprehend.detect_pii_entities(Text=text, LanguageCode="en")["Entities"]
    phrases = comprehend.detect_key_phrases(Text=text, LanguageCode="en")["KeyPhrases"]

    extra = backstop_spans(text, pii)
    redacted, skipped = redact(text, pii + extra)

    out = {
        "language": {"code": language["LanguageCode"], "score": round(language["Score"], 3)},
        "entities": [
            {"type": e["Type"], "text": e["Text"], "score": round(e["Score"], 3)}
            for e in entities
        ],
        "pii": [
            {"type": e["Type"], "score": round(e["Score"], 3),
             "span": [e["BeginOffset"], e["EndOffset"]],
             "source": e.get("Source", "comprehend")}
            for e in sorted(pii + extra, key=lambda e: e["BeginOffset"])
        ],
        "backstop_caught": [
            {"type": e["Type"], "text": text[e["BeginOffset"]:e["EndOffset"]]}
            for e in extra
        ],
        "pii_skipped_below_threshold": skipped,
        "key_phrases": [p["Text"] for p in sorted(phrases, key=lambda p: -p["Score"])[:8]],
        "redacted_text": redacted,
    }

    # Sentiment on a form is noise. "Invoice Number INV-2026-0417" has no
    # sentiment, and reporting one invites someone to act on it.
    if want_sentiment:
        sentiment = comprehend.detect_sentiment(Text=text, LanguageCode="en")
        out["sentiment"] = {
            "label": sentiment["Sentiment"],
            "scores": {k: round(v, 3) for k, v in sentiment["SentimentScore"].items()},
        }

    return out


def main() -> None:
    comprehend = client()
    textract = json.loads((RESULTS / "textract.json").read_text())
    out = {}

    for name, doc in textract.items():
        result = analyse(comprehend, doc["text"], want_sentiment=(name == "letter"))
        out[name] = result

        types = sorted({p["type"] for p in result["pii"]})
        caught = result["backstop_caught"]
        units = max(3, -(-len(doc["text"]) // 100))  # 300-char minimum, 4 calls
        print(f"  {name:9} entities {len(result['entities']):2}  "
              f"pii {len(result['pii']):2} {types}  "
              f"~{units * 4} billable units"
              + (f"  sentiment {result['sentiment']['label']}" if "sentiment" in result else ""))
        if caught:
            print(f"            backstop caught {len(caught)} Comprehend missed: "
                  f"{[c['type'] for c in caught]}")
        if result["pii_skipped_below_threshold"]:
            print(f"            {len(result['pii_skipped_below_threshold'])} PII hit(s) "
                  f"below {REDACT_THRESHOLD} confidence, not redacted")

    (RESULTS / "comprehend.json").write_text(json.dumps(out, indent=2) + "\n")
    print("\nwritten to results/comprehend.json")


if __name__ == "__main__":
    main()
