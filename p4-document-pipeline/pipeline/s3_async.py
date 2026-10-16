"""The async path: documents in S3, results collected by polling a job.

Nothing in this project needs it. The documents are single-page PNGs and the
sync API handles those from local bytes with nothing left behind. This exists
because the async path is the one a real pipeline uses, and the differences are
not obvious from the documentation.

What actually changes:

**Multi-page.** Sync takes one page. Async takes a multi-page PDF or TIFF and
returns every page in one job. This is the real reason to use it; everything
else is a consequence.

**S3 is mandatory.** Async reads from a bucket. That is a resource that
persists, costs storage, and has to be torn down, which is why TEARDOWN.md
exists and why the bucket name lives in a gitignored file.

**It is a job, not a call.** StartDocumentAnalysis returns a JobId straight
away and the work happens later. You poll, or you have it notify an SNS topic.
That makes the whole thing asynchronous all the way up: no request thread waits
for it, and the code that handles the result is not the code that started it.

**Results are paginated.** A long document's blocks arrive across pages joined
by NextToken, and forgetting to follow them truncates the output silently.

**It is not cheaper.** AsyncFormsQueriesTablesPagesProcessed is $0.07 a page
and the sync equivalent is $0.07 a page. The choice is about document shape and
architecture, never about price.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CONFIG = ROOT / "config"
RESULTS = ROOT / "results"

POLL_SECONDS = 3
MAX_POLLS = 40


def local_config() -> dict:
    path = CONFIG / "local.json"
    if not path.exists():
        raise SystemExit(
            "config/local.json is missing. Copy config/local.example.json and "
            "set your own bucket name."
        )
    return json.loads(path.read_text())


def upload(s3, bucket: str, prefix: str, path: Path) -> str:
    key = f"{prefix}{path.name}"
    s3.upload_file(str(path), bucket, key)
    return key


def start(textract, bucket: str, key: str, queries: list[tuple[str, str]]) -> str:
    response = textract.start_document_analysis(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
        FeatureTypes=["QUERIES"],
        QueriesConfig={"Queries": [
            {"Text": question, "Alias": alias} for alias, question in queries
        ]},
    )
    return response["JobId"]


def collect(textract, job_id: str) -> tuple[list[dict], float]:
    """Poll to completion, then follow NextToken to the end of the blocks."""
    started = time.perf_counter()

    for _ in range(MAX_POLLS):
        response = textract.get_document_analysis(JobId=job_id)
        status = response["JobStatus"]
        if status == "SUCCEEDED":
            break
        if status == "FAILED":
            raise RuntimeError(f"job {job_id} failed: {response.get('StatusMessage')}")
        time.sleep(POLL_SECONDS)
    else:
        raise TimeoutError(f"job {job_id} still {status} after "
                           f"{MAX_POLLS * POLL_SECONDS}s")

    blocks = response["Blocks"]
    token = response.get("NextToken")
    while token:
        page = textract.get_document_analysis(JobId=job_id, NextToken=token)
        blocks.extend(page["Blocks"])
        token = page.get("NextToken")

    return blocks, (time.perf_counter() - started)


def main() -> None:
    from pipeline.extract import QUERIES, extract_queries

    config = local_config()
    bucket, prefix = config["bucket"], config["prefix"]
    session = boto3.Session(profile_name="personal", region_name="us-east-1")
    s3, textract = session.client("s3"), session.client("textract")

    out = {}
    for name, queries in QUERIES.items():
        path = DOCS / f"{name}.png"
        key = upload(s3, bucket, prefix, path)
        job_id = start(textract, bucket, key, queries)
        blocks, elapsed = collect(textract, job_id)

        answers = extract_queries({"Blocks": blocks})
        answered = sum(1 for a in answers.values() if a["answer"])

        out[name] = {
            "s3_key": key,
            "job_id": job_id,
            "wall_seconds": round(elapsed, 1),
            "blocks": len(blocks),
            "queries": answers,
        }
        print(f"  {name:9} job started, {elapsed:5.1f}s to SUCCEEDED, "
              f"{len(blocks):4} blocks, queries {answered}/{len(answers)}")

    (RESULTS / "textract_async.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwritten to results/textract_async.json")
    print(f"{len(out)} objects now in s3://<bucket>/{prefix} -- see TEARDOWN.md")


if __name__ == "__main__":
    main()
