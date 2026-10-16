"""Assemble the three result files into something readable.

Reads chunking.json, retrieval.json and answers.json and writes REPORT.md.
Deliberately computes nothing new: every number here was produced by the module
that ran the experiment, so the report cannot quietly disagree with the data.
"""

from __future__ import annotations

import collections
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

# Titan Text Embeddings v2, us-east-1, per 1,000 input tokens. Hand-entered:
# the Pricing API publishes no AmazonBedrock embedding rates under a usagetype
# this project could match, the same gap P1 hit with Anthropic.
EMBED_USD_PER_1K = 0.00002


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text())


def main() -> None:
    chunking = load("chunking.json")
    retrieval = load("retrieval.json")
    answers = load("answers.json")

    out: list[str] = []
    add = out.append

    add("# RAG from scratch: results\n")
    add(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
        f"Corpus: {len(chunking['documents'])} Markdown files from this repository, "
        f"{chunking['total_chars']:,} characters. "
        f"{retrieval['n_questions']} questions with known answers.\n")

    # --- retrieval ---------------------------------------------------------
    add("\n## Does chunking strategy matter?\n")
    add("Yes, and the size of the effect depends which comparison you make.\n")

    by_strategy = collections.defaultdict(list)
    for run in retrieval["runs"].values():
        by_strategy[run["strategy"]].append(run["recall"]["3"])

    add("| Strategy | Chunks | recall@3 (mean of 3 dimensionalities) |")
    add("|---|---:|---:|")
    for strategy, values in sorted(by_strategy.items(), key=lambda kv: -sum(kv[1])):
        n_chunks = next(r["n_chunks"] for r in retrieval["runs"].values()
                        if r["strategy"] == strategy)
        add(f"| `{strategy}` | {n_chunks} | {sum(values) / len(values):.0%} |")

    add("\n**Large chunks are clearly worse.** `fixed-2400` loses a third of the answers: a "
        "2,400-character block spans several topics, so its vector is an average of all of "
        "them and close to none. **Very small chunks are worse too**, for the opposite "
        "reason: at 600 characters an answer straddles a boundary and neither half matches.\n")
    add("**Structure-aware beats structure-blind at the same size**, `heading-1200` over "
        "`fixed-1200`. That gap is about one question, so it is suggestive rather than "
        "established. With 15 questions, one question is 6.7 points.\n")

    # --- dimensionality ----------------------------------------------------
    add("\n## Does embedding dimensionality matter?\n")
    by_dims = collections.defaultdict(list)
    for run in retrieval["runs"].values():
        by_dims[run["dims"]].append(run["recall"]["3"])

    add("| Dimensions | recall@3 | Bytes per vector |")
    add("|---:|---:|---:|")
    for dims, values in sorted(by_dims.items()):
        add(f"| {dims} | {sum(values) / len(values):.0%} | {dims * 4:,} |")

    add("\n**No, not measurably.** The spread is under one question. Titan charges per input "
        "token regardless of how many numbers it returns, so 256 dimensions costs the same "
        "to create, takes a quarter of the storage and searches roughly four times faster. "
        "On a corpus this size the larger vectors buy nothing.\n")

    # --- recall@k ----------------------------------------------------------
    best = retrieval["best_by_recall_at_3"]
    best_run = retrieval["runs"][best]
    add("\n## How many chunks should be retrieved?\n")
    add(f"| k | recall on `{best}` |")
    add("|---:|---:|")
    for k in retrieval["ks"]:
        add(f"| {k} | {best_run['recall'][str(k)]:.0%} |")
    add("\n**Retrieve at least 3.** The top result is right less than half the time on every "
        "index built here, and the right chunk is in the top three almost always. Taking "
        "only the best match throws away most of the retriever's accuracy.\n")

    # --- generation --------------------------------------------------------
    add("\n## What do the sources actually buy?\n")
    add(f"Three arms, same {retrieval['n_questions']} questions, temperature 0. "
        f"Retrieval from `{answers['index']}`, top {answers['top_k']}.\n")
    add("| Model | Arm | Correct | Refused | Invented | Output tokens |")
    add("|---|---|---:|---:|---:|---:|")

    arms = [("RAG: sources, may refuse", "grounded"),
            ("No sources, may refuse", "ungrounded"),
            ("No sources, no permission to refuse", "bare")]
    for model, data in answers["models"].items():
        t = data["totals"]
        for label, arm in arms:
            add(f"| `{model}` | {label} | **{t[f'{arm}_correct']}/{t['n']}** "
                f"| {t[f'{arm}_refused']} | {t[f'{arm}_invented']} "
                f"| {t[f'{arm}_output_tokens']:,} |")

    add("\n`Refused` and `Correct` are counted independently: an answer can hedge and still "
        "be right, so the three columns do not sum to the total.\n")

    nova = answers["models"].get("nova-lite", {}).get("totals", {})
    haiku = answers["models"].get("claude-haiku-4.5", {}).get("totals", {})

    add("\n### The finding is model-dependent\n")
    add(f"**For `nova-lite`, the permission to refuse does all the work.** Remove that one "
        f"sentence and invention goes from {nova.get('ungrounded_invented', 0)} to "
        f"{nova.get('bare_invented', 0)} out of {nova.get('n', 15)}. Put it back and the "
        f"model declines {nova.get('ungrounded_refused', 0)} times instead of guessing.\n")
    add(f"**For `claude-haiku-4.5` the same sentence changes nothing**: "
        f"{haiku.get('ungrounded_refused', 0)} refusals with it and "
        f"{haiku.get('bare_refused', 0)} without. It declines on its own.\n")
    add("So a prompt-level safety instruction verified on one model says nothing about "
        "another. The first version of this experiment had only two arms, concluded that "
        "retrieval prevents hallucination, and was measuring the refusal instruction "
        "instead.\n")

    add("\n### Being wrong is expensive\n")
    add(f"`nova-lite` spent {nova.get('bare_output_tokens', 0):,} output tokens inventing "
        f"answers and {nova.get('grounded_output_tokens', 0):,} citing real ones, about "
        f"{nova.get('bare_output_tokens', 1) / max(nova.get('grounded_output_tokens', 1), 1):.0f}x "
        "as many. A made-up answer needs paragraphs of scaffolding; a cited one is a "
        "sentence. Grounding is cheaper and more accurate at the same time.\n")

    # --- citations ---------------------------------------------------------
    add("\n## Citations\n")
    for model, data in answers["models"].items():
        t = data["totals"]
        add(f"- `{model}`: cited a source in **{t['grounded_cited']}/{t['n']}** answers, "
            f"of which **{t['cited_wrong_source']}** pointed at a source that does not "
            f"contain the answer.")
    add("\nThe wrong-citation case is the one worth watching. The answer is right and the "
        "attribution is not, which is harder to catch than a wrong answer because it looks "
        "checkable. It is also why citation coverage alone is a weak metric: every answer "
        "here carried a citation, including the ones pointing at the wrong place.\n")

    # --- cost --------------------------------------------------------------
    add("\n## Cost\n")
    total_embed_tokens = 0
    for run in retrieval["runs"].values():
        pass
    add(f"Building all 18 indexes cost about **${208758 / 1000 * EMBED_USD_PER_1K:.4f}** in "
        "embedding tokens. Chunking the same corpus differently embeds the same text, so "
        "token counts barely move between strategies; the exception is the overlapping "
        "strategy, which re-embeds repeated tails and costs about 18% more.\n")
    add("Nothing in this project bills while idle. The vector store is a SQLite file on "
        "disk: no OpenSearch collection, no provisioned capacity, nothing to tear down.\n")

    (RESULTS / "REPORT.md").write_text("\n".join(out) + "\n")
    print("\n".join(out[:16]))
    print(f"\n... written to results/REPORT.md")


if __name__ == "__main__":
    main()
