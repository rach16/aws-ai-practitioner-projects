"""Textract: pixels to structure.

Three feature types are requested in one AnalyzeDocument call, because they
answer different questions about the same page and are priced per feature, so
asking for all three once is cheaper than three calls.

  FORMS    key/value pairs, the "Invoice Number: INV-2026-0417" shape
  TABLES   rows and columns, with cells addressed by row and column index
  QUERIES  a plain question, answered with a confidence score

QUERIES is the one worth knowing about. FORMS depends on the document actually
labelling its fields, and on Textract pairing the label with the right value;
on the AWS sample paystub it split one table header three ways and the TABLES
feature merged the same header into one cell. Asking "what is the net pay?" and
getting an answer with a confidence attached is both more robust and easier to
act on, because a low confidence is something a pipeline can route to review.

Everything here is synchronous and sends the image as bytes. No S3, nothing
left behind. The async path through S3 lives in s3_async.py, which exists to
show the difference rather than because these documents need it.
"""

from __future__ import annotations

import json
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
RESULTS = ROOT / "results"

# What to ask each document. Phrased the way a person would ask, which is what
# the feature is tuned for; "net_pay_usd" scores far worse than "net pay".
QUERIES = {
    "invoice": [
        ("invoice_number", "What is the invoice number?"),
        ("invoice_date", "What is the invoice date?"),
        ("due_date", "What is the due date?"),
        ("vendor_name", "Who is the vendor?"),
        ("customer_name", "Who is the invoice billed to?"),
        ("total_usd", "What is the total due?"),
        ("subtotal_usd", "What is the subtotal?"),
        ("tax_usd", "How much tax?"),
        ("contact_email", "What is the contact email address?"),
        ("contact_phone", "What is the contact phone number?"),
    ],
    "paystub": [
        ("employee_name", "What is the employee name?"),
        ("employee_id", "What is the employee ID?"),
        ("ssn", "What is the social security number?"),
        ("pay_period_end", "What is the pay period ending date?"),
        ("gross_pay_usd", "What is the gross pay?"),
        ("net_pay_usd", "What is the net pay?"),
        ("employer_name", "Who is the employer?"),
    ],
    "letter": [
        ("sender_name", "Who wrote the letter?"),
        ("recipient_name", "Who is the letter addressed to?"),
        ("letter_date", "What is the date of the letter?"),
        ("clinic_name", "What is the name of the clinic?"),
        ("appointment_date", "What is the date of the next appointment?"),
    ],
}


def client():
    return boto3.Session(profile_name="personal", region_name="us-east-1").client("textract")


def analyse(textract, image_bytes: bytes, queries: list[tuple[str, str]]) -> dict:
    response = textract.analyze_document(
        Document={"Bytes": image_bytes},
        FeatureTypes=["FORMS", "TABLES", "QUERIES"],
        QueriesConfig={"Queries": [
            {"Text": question, "Alias": alias} for alias, question in queries
        ]},
    )
    return response


def index_blocks(response: dict) -> dict[str, dict]:
    return {block["Id"]: block for block in response["Blocks"]}


def text_of(block: dict, blocks: dict[str, dict]) -> str:
    """Walk a block's CHILD relationships to assemble its text.

    Textract returns a flat list of blocks joined by id, not a tree, so every
    value has to be reassembled from the words it points at. SELECTION_ELEMENT
    children are checkboxes and contribute a marker rather than text.
    """
    parts: list[str] = []
    for relationship in block.get("Relationships", []):
        if relationship["Type"] != "CHILD":
            continue
        for child_id in relationship["Ids"]:
            child = blocks[child_id]
            if child["BlockType"] == "WORD":
                parts.append(child["Text"])
            elif child["BlockType"] == "SELECTION_ELEMENT":
                if child.get("SelectionStatus") == "SELECTED":
                    parts.append("[X]")
    return " ".join(parts)


def extract_forms(response: dict) -> list[dict]:
    """KEY_VALUE_SET blocks, paired up by their VALUE relationship."""
    blocks = index_blocks(response)
    pairs = []
    for block in response["Blocks"]:
        if block["BlockType"] != "KEY_VALUE_SET":
            continue
        if "KEY" not in block.get("EntityTypes", []):
            continue
        key = text_of(block, blocks)
        value = ""
        value_confidence = None
        for relationship in block.get("Relationships", []):
            if relationship["Type"] == "VALUE":
                for value_id in relationship["Ids"]:
                    value_block = blocks[value_id]
                    value = text_of(value_block, blocks)
                    value_confidence = round(value_block.get("Confidence", 0), 2)
        pairs.append({"key": key, "value": value,
                      "key_confidence": round(block.get("Confidence", 0), 2),
                      "value_confidence": value_confidence})
    return pairs


def extract_tables(response: dict) -> list[list[list[str]]]:
    """Each table as a list of rows, each row a list of cell strings."""
    blocks = index_blocks(response)
    tables = []
    for block in response["Blocks"]:
        if block["BlockType"] != "TABLE":
            continue
        cells: dict[tuple[int, int], str] = {}
        for relationship in block.get("Relationships", []):
            if relationship["Type"] != "CHILD":
                continue
            for cell_id in relationship["Ids"]:
                cell = blocks[cell_id]
                if cell["BlockType"] != "CELL":
                    continue
                cells[(cell["RowIndex"], cell["ColumnIndex"])] = text_of(cell, blocks)
        if not cells:
            continue
        rows = max(r for r, _ in cells)
        cols = max(c for _, c in cells)
        tables.append([[cells.get((r, c), "") for c in range(1, cols + 1)]
                       for r in range(1, rows + 1)])
    return tables


def extract_queries(response: dict) -> dict[str, dict]:
    """Query answers keyed by alias, with the confidence Textract attached."""
    blocks = index_blocks(response)
    answers = {}
    for block in response["Blocks"]:
        if block["BlockType"] != "QUERY":
            continue
        alias = block["Query"].get("Alias") or block["Query"]["Text"]
        answer, confidence = None, None
        for relationship in block.get("Relationships", []):
            if relationship["Type"] == "ANSWER":
                for answer_id in relationship["Ids"]:
                    result = blocks[answer_id]
                    answer = result.get("Text")
                    confidence = round(result.get("Confidence", 0), 2)
        answers[alias] = {"answer": answer, "confidence": confidence}
    return answers


def plain_text(response: dict) -> str:
    """Every LINE in reading order. This is what gets handed to Comprehend."""
    return "\n".join(b["Text"] for b in response["Blocks"] if b["BlockType"] == "LINE")


def main() -> None:
    textract = client()
    RESULTS.mkdir(exist_ok=True)
    out = {}

    for name, queries in QUERIES.items():
        path = DOCS / f"{name}.png"
        response = analyse(textract, path.read_bytes(), queries)

        pages = response["DocumentMetadata"]["Pages"]
        answers = extract_queries(response)
        forms = extract_forms(response)
        tables = extract_tables(response)
        text = plain_text(response)

        out[name] = {
            "pages": pages,
            "queries": answers,
            "forms": forms,
            "tables": tables,
            "text": text,
            "block_count": len(response["Blocks"]),
        }

        answered = sum(1 for a in answers.values() if a["answer"])
        low = [k for k, a in answers.items()
               if a["confidence"] is not None and a["confidence"] < 90]
        print(f"  {name:9} {pages} page  {len(response['Blocks']):4} blocks  "
              f"queries {answered}/{len(answers)}  forms {len(forms):2}  "
              f"tables {len(tables)}  {len(text)} chars"
              + (f"  low-confidence: {low}" if low else ""))

    (RESULTS / "textract.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwritten to results/textract.json")


if __name__ == "__main__":
    main()
