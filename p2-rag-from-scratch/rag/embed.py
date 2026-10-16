"""Turn chunks into vectors with Titan, and build every index to be compared.

Titan Text Embeddings v2 takes a `dimensions` argument of 256, 512 or 1024.
That is not a quality dial with a cost attached: **you pay the same per token
whichever you pick**, because the model reads the same text either way. What
changes is storage and search time, and whatever accuracy is lost by having
fewer numbers to describe the same meaning.

Titan v2 is trained so that the shorter outputs are usable on their own rather
than being a truncation you are expected to regret, which is a claim worth
testing rather than believing, and evaluate.py tests it.

One call per chunk. Titan's text embedding API takes a single string, so there
is no batching to be had: 78 chunks is 78 calls. That is the main reason an
index build takes a minute rather than a second, and it is a real
consideration at a corpus of any size.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import boto3
import numpy as np

import rag._path  # noqa: F401
from rag.corpus import STRATEGIES, build
from rag.store import ROOT, connect, list_runs, run_id, save_run

MODEL_ID = "amazon.titan-embed-text-v2:0"
DIMENSIONS = [256, 512, 1024]


def client():
    return boto3.Session(profile_name="personal", region_name="us-east-1").client("bedrock-runtime")


def embed_one(bedrock, text: str, dims: int) -> tuple[np.ndarray, int]:
    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": dims, "normalize": True}),
    )
    payload = json.loads(response["body"].read())
    return np.array(payload["embedding"], dtype=np.float32), payload.get("inputTextTokenCount", 0)


def embed_many(bedrock, texts: list[str], dims: int) -> tuple[np.ndarray, int]:
    vectors, tokens = [], 0
    for text in texts:
        vector, used = embed_one(bedrock, text, dims)
        vectors.append(vector)
        tokens += used
    return np.vstack(vectors), tokens


def main() -> None:
    bedrock = client()
    conn = connect()

    print(f"{MODEL_ID}\n")
    print(f"  {'index':28} {'chunks':>7} {'tokens':>8} {'seconds':>8} {'MB':>6}")
    print(f"  {'-' * 28} {'-' * 7} {'-' * 8} {'-' * 8} {'-' * 6}")

    for strategy in STRATEGIES:
        chunks = build(strategy)
        for dims in DIMENSIONS:
            rid = run_id(strategy, dims)
            started = time.perf_counter()
            vectors, tokens = embed_many(bedrock, [c.text for c in chunks], dims)
            elapsed = time.perf_counter() - started

            save_run(conn, rid, strategy, MODEL_ID, dims, chunks, vectors, tokens,
                     datetime.now(timezone.utc).isoformat(timespec="seconds"))

            megabytes = vectors.nbytes / 1_048_576
            print(f"  {rid:28} {len(chunks):>7} {tokens:>8,} {elapsed:>8.1f} {megabytes:>6.3f}")

    runs = list_runs(conn)
    total_tokens = sum(r["input_tokens"] for r in runs)
    # Titan Text Embeddings v2, us-east-1, published rate per 1,000 input tokens.
    cost = total_tokens / 1000 * 0.00002
    print(f"\n  {len(runs)} indexes, {total_tokens:,} input tokens total, about ${cost:.4f}")
    print(f"  stored in results/{ 'vectors.db' }")


if __name__ == "__main__":
    main()
