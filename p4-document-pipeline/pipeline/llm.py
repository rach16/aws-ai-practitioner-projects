"""The other way to do it: hand the text to a foundation model and ask.

Textract Queries and a model prompted for JSON are solving the same problem
from opposite ends, and the point of running both is that the trade is real
rather than obvious.

To keep the comparison fair, the model gets **exactly** what Textract Queries
got: the same page, read by the same OCR, with the same fields requested in
the same words. The only variable is what does the understanding. Giving the
model the original image instead would measure a different thing, and giving
it a better-worded prompt would measure my prompt engineering.

The models are the two P1 picked out: nova-lite, which tied for the best score
at the lowest cost, and claude-haiku-4.5, which took the JSON extraction column
outright. P1 said Haiku is the one to beat at structured extraction, and this
is the test of whether that held outside a twenty-question suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pipeline._path  # noqa: F401
from pipeline.extract import QUERIES
from shared.bedrock import client as bedrock_client
from shared.bedrock import converse

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

MODELS = {
    "nova-lite": "amazon.nova-lite-v1:0",
    "claude-haiku-4.5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}

SYSTEM = (
    "You extract fields from documents. Reply with a single JSON object mapping "
    "each requested field name to the value you find, and nothing else. No markdown "
    "fences, no commentary. Use null for a field that is genuinely not present in "
    "the document. Do not guess."
)


def prompt_for(doc_text: str, fields: list[tuple[str, str]]) -> str:
    asks = "\n".join(f"- {alias}: {question}" for alias, question in fields)
    return (
        f"Extract these fields:\n{asks}\n\n"
        f"Document text:\n---\n{doc_text}\n---\n\n"
        f"Reply with a JSON object whose keys are exactly: "
        f"{', '.join(alias for alias, _ in fields)}"
    )


def parse_json(text: str) -> dict | None:
    """Find the first balanced object, tolerating a fence the model was told not to add."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, char in enumerate(text[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def main() -> None:
    textract = json.loads((RESULTS / "textract.json").read_text())
    bedrock = bedrock_client()
    out: dict[str, dict] = {}

    for model_key, model_id in MODELS.items():
        out[model_key] = {}
        for doc_name, fields in QUERIES.items():
            response = converse(
                bedrock, model_id,
                prompt_for(textract[doc_name]["text"], fields),
                system=SYSTEM, max_tokens=800, temperature=0.0,
            )

            if not response.ok:
                out[model_key][doc_name] = {"error": response.error}
                print(f"  {model_key:18} {doc_name:9} ERROR {response.error[:60]}")
                continue

            parsed = parse_json(response.text)
            nulls = sum(1 for v in (parsed or {}).values() if v is None)
            out[model_key][doc_name] = {
                "fields": parsed,
                "raw": response.text if parsed is None else None,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "server_latency_ms": response.server_latency_ms,
            }
            print(f"  {model_key:18} {doc_name:9} "
                  f"{'parsed' if parsed else 'UNPARSEABLE':12} "
                  f"{len(parsed or {})} fields, {nulls} null  "
                  f"{response.input_tokens:4}in/{response.output_tokens:3}out  "
                  f"{response.server_latency_ms}ms")

    (RESULTS / "llm.json").write_text(json.dumps(out, indent=2) + "\n")
    print("\nwritten to results/llm.json")


if __name__ == "__main__":
    main()
