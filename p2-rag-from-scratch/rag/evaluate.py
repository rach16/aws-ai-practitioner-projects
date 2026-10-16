"""Does retrieval actually find the answer? Measured, for all 18 indexes.

The metric is **recall@k**: for each question, does any chunk containing the
marker appear in the top k results. Not precision, because for RAG the
question that matters is whether the answer reached the model at all. A
retriever that returns the right chunk alongside four irrelevant ones has
succeeded; the generator can ignore the other four. One that misses it has
failed no matter how tidy the rest of the list is.

Two things this deliberately does not do.

It does not score the generated answer here. Retrieval and generation fail for
different reasons and mixing them produces a number that cannot be acted on.
answer.py handles generation, against the index this file picks.

It does not use an embedding-similarity threshold. A cosine score of 0.7 means
nothing in the abstract: it depends on the model, the dimensionality and how
the corpus happens to be distributed. Rank is comparable across runs in a way
that raw score is not.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

import rag._path  # noqa: F401
from rag.embed import client, embed_one
from rag.store import ROOT, connect, cosine_search, list_runs, load_run

KS = (1, 3, 5)


def load_questions() -> list[dict]:
    return json.loads((ROOT / "config" / "questions.json").read_text())["questions"]


def main() -> None:
    questions = load_questions()
    conn = connect()
    runs = list_runs(conn)
    bedrock = client()

    # Each question is embedded once per dimensionality, not once per index.
    # The query vector does not depend on how the corpus was chunked, and six
    # strategies share each of three dimensionalities.
    dims_needed = sorted({r["dims"] for r in runs})
    query_vectors: dict[int, dict[str, np.ndarray]] = {}
    for dims in dims_needed:
        query_vectors[dims] = {
            q["id"]: embed_one(bedrock, q["question"], dims)[0] for q in questions
        }
    print(f"{len(questions)} questions embedded at {dims_needed} dimensions\n")

    results = {}
    header = "  ".join(f"r@{k}" for k in KS)
    print(f"  {'index':28} {'chunks':>6}  {header}   {'ms':>6}")
    print(f"  {'-' * 28} {'-' * 6}  {'-' * len(header)}   {'-' * 6}")

    for run in runs:
        rid = run["run_id"]
        meta, matrix = load_run(conn, rid)
        gold = {
            q["id"]: {i for i, m in enumerate(meta) if q["gold_marker"] in m["text"]}
            for q in questions
        }

        ranks, elapsed = {}, 0.0
        for q in questions:
            started = time.perf_counter()
            hits = cosine_search(query_vectors[run["dims"]][q["id"]], matrix, max(KS))
            elapsed += (time.perf_counter() - started) * 1000
            found = [r for r, (i, _) in enumerate(hits) if i in gold[q["id"]]]
            ranks[q["id"]] = min(found) if found else None

        recall = {k: sum(1 for r in ranks.values() if r is not None and r < k) / len(questions)
                  for k in KS}
        results[rid] = {
            "strategy": run["strategy"], "dims": run["dims"],
            "n_chunks": run["n_chunks"], "recall": recall,
            "ranks": ranks,
            "search_ms_mean": round(elapsed / len(questions), 3),
            "missed_at_5": [qid for qid, r in ranks.items() if r is None],
        }

        cells = "  ".join(f"{recall[k]:.0%}".rjust(4) for k in KS)
        print(f"  {rid:28} {run['n_chunks']:>6}  {cells}   "
              f"{results[rid]['search_ms_mean']:>6.2f}")

    best = max(results, key=lambda r: (results[r]["recall"][3], -results[r]["dims"]))
    print(f"\n  best recall@3: {best} at {results[best]['recall'][3]:.0%}")

    never = set.intersection(*(set(v["missed_at_5"]) for v in results.values())) \
        if results else set()
    if never:
        print(f"  never retrieved by any index at k=5: {sorted(never)}")

    (ROOT / "results" / "retrieval.json").write_text(json.dumps({
        "ks": list(KS), "n_questions": len(questions),
        "best_by_recall_at_3": best, "runs": results,
    }, indent=2) + "\n")
    print("\n  written to results/retrieval.json")


if __name__ == "__main__":
    main()
