"""Generation: paste the retrieved chunks above the question, and insist on citations.

After retrieval this part is short, and that is the honest shape of RAG. Find
the paragraphs, put them in the prompt, tell the model to use only those and to
say which one it used. The engineering is all in the first step.

Three things the prompt does, each for a reason that shows up in the numbers:

**Only from the sources.** Without it the model answers from whatever it
absorbed in training, which for a question about this repository means
inventing something plausible. The ungrounded run below measures exactly that.

**Cite the source number.** A citation is the only evidence a reader has that
retrieval worked at all. An answer with no citation cannot be distinguished
from an answer the model made up, and silent retrieval failure looks like a
model that is slightly too cautious.

**Say you do not know.** Refusal has to be offered explicitly or it is not
available: a model asked a question will answer it. This is also the hardest
instruction to make stick, and `cited_wrong_source` below is where it fails
in a subtler way, by answering correctly and attributing it to the wrong place.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import rag._path  # noqa: F401
from rag.search import Index
from rag.store import ROOT, connect
from shared.bedrock import client as bedrock_client
from shared.bedrock import converse

MODELS = {
    "nova-lite": "amazon.nova-lite-v1:0",
    "claude-haiku-4.5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}

INDEX = "heading-1200@512"   # best recall@3 in results/retrieval.json
TOP_K = 3

SYSTEM = (
    "Answer only from the sources provided. Cite the source number you used, "
    "like [1]. If the sources do not contain the answer, say you do not know. "
    "Be brief."
)

# Two controls, not one. The first version compared RAG against "no sources but
# you may refuse", concluded that RAG prevents hallucination, and was wrong:
# both models mostly refused rather than invented, so what the comparison
# actually measured was the refusal instruction.
#
# Separating them shows which intervention does which job. Permission to refuse
# stops the invention; the sources supply the answer. They are different fixes
# and conflating them credits RAG with something a sentence of prompt did.
SYSTEM_NO_RAG = (
    "Answer the question. If you do not know, say you do not know. Be brief."
)
SYSTEM_BARE = "Answer the question."


def load_questions() -> list[dict]:
    return json.loads((ROOT / "config" / "questions.json").read_text())["questions"]


def build_prompt(question: str, hits) -> str:
    blocks = "\n\n".join(
        f"--- SOURCE {h.rank + 1}: {h.source} · {h.heading} ---\n{h.text}" for h in hits
    )
    return f"{question}\n\n{blocks}"


def groups_satisfied(answer: str, groups: list[list[str]]) -> bool:
    """Every group must be satisfied by at least one of its alternatives.

    Groups are deliberately loose. The first version demanded particular words
    and rejected three answers that were plainly correct, for example marking
    "did not account for credential resolution and the TLS handshake on a cold
    client" wrong because it lacked the literal number 231. That measures how
    closely a model echoes the source, not whether it answered the question,
    and it flattered the more verbose model.
    """
    low = answer.lower()
    return all(any(alt.lower() in low for alt in group) for group in groups)


# Models decline in many more ways than "I do not know", and the first version
# of this pattern caught about a fifth of them. It reported confident
# hallucination where the model had actually said "I don't have enough context
# to answer this question", which inverted the conclusion of the whole run.
REFUSAL = re.compile(
    r"(do not know|don\'t know|don\u2019t know|cannot determine|can\'t determine|"
    r"not (?:contain|provide|include)|no information|unable to (?:determine|answer|find)|"
    r"not (?:found|present) in the sources|"
    r"(?:do not|don\'t|don\u2019t) have (?:enough |sufficient |any )?(?:context|information)|"
    r"need more (?:context|information|details)|"
    r"could you (?:provide|clarify|specify)|"
    r"(?:not|no) (?:enough|sufficient) (?:context|information)|"
    r"which (?:system|model|project|invoice|document) (?:you|are you) ?(?:are )?referring to|"
    r"unclear (?:what|which)|"
    r"I(?:'m| am) not (?:sure|aware|familiar))",
    re.I,
)


def cited_numbers(answer: str) -> set[int]:
    return {int(n) for n in re.findall(r"\[(\d+)\]", answer)}


def main() -> None:
    questions = load_questions()
    conn = connect()
    bedrock = bedrock_client()
    index = Index(conn, INDEX, bedrock=bedrock)

    results = {}

    for model_key, model_id in MODELS.items():
        rows = []
        for q in questions:
            hits = index.search(q["question"], k=TOP_K)
            gold_ranks = {h.rank + 1 for h in hits if q["gold_marker"] in h.text}

            grounded = converse(bedrock, model_id, build_prompt(q["question"], hits),
                                system=SYSTEM, max_tokens=400, temperature=0.0)
            ungrounded = converse(bedrock, model_id, q["question"],
                                  system=SYSTEM_NO_RAG, max_tokens=400, temperature=0.0)
            bare = converse(bedrock, model_id, q["question"],
                            system=SYSTEM_BARE, max_tokens=400, temperature=0.0)

            g_text = grounded.text if grounded.ok else ""
            u_text = ungrounded.text if ungrounded.ok else ""
            b_text = bare.text if bare.ok else ""
            cites = cited_numbers(g_text)

            rows.append({
                "id": q["id"],
                "question": q["question"],
                "retrieved_gold": bool(gold_ranks),
                "gold_ranks": sorted(gold_ranks),
                "grounded": {
                    "correct": groups_satisfied(g_text, q["answer_must_contain"]),
                    "cited": sorted(cites),
                    # Answering correctly while pointing at a source that does not
                    # support it. Looks checkable, is not.
                    "cited_wrong_source": bool(cites) and bool(gold_ranks)
                                          and not (cites & gold_ranks),
                    "refused": bool(REFUSAL.search(g_text)),
                    "output_tokens": grounded.output_tokens,
                    "input_tokens": grounded.input_tokens,
                    "text": g_text,
                },
                "ungrounded": {
                    "correct": groups_satisfied(u_text, q["answer_must_contain"]),
                    "refused": bool(REFUSAL.search(u_text)),
                    "output_tokens": ungrounded.output_tokens,
                    "input_tokens": ungrounded.input_tokens,
                    "text": u_text,
                },
                "bare": {
                    "correct": groups_satisfied(b_text, q["answer_must_contain"]),
                    "refused": bool(REFUSAL.search(b_text)),
                    "output_tokens": bare.output_tokens,
                    "input_tokens": bare.input_tokens,
                    "text": b_text,
                },
            })

            def flag(arm):
                row = rows[-1][arm]
                if row["correct"]:
                    return "correct "
                return "refused " if row["refused"] else "INVENTED"

            print(f"  {model_key:17} {q['id']:4} "
                  f"rag={flag('grounded')}  "
                  f"may-refuse={flag('ungrounded')}  "
                  f"bare={flag('bare')}  cites={sorted(cites) or '-'}")

        n = len(rows)
        results[model_key] = {
            "rows": rows,
            "totals": {
                "retrieved_gold": sum(r["retrieved_gold"] for r in rows),
                "grounded_correct": sum(r["grounded"]["correct"] for r in rows),
                "grounded_cited": sum(bool(r["grounded"]["cited"]) for r in rows),
                "cited_wrong_source": sum(r["grounded"]["cited_wrong_source"] for r in rows),
                "grounded_refused": sum(r["grounded"]["refused"] for r in rows),
                "ungrounded_correct": sum(r["ungrounded"]["correct"] for r in rows),
                "ungrounded_refused": sum(r["ungrounded"]["refused"] for r in rows),
                "bare_correct": sum(r["bare"]["correct"] for r in rows),
                "bare_refused": sum(r["bare"]["refused"] for r in rows),
                "bare_output_tokens": sum(r["bare"]["output_tokens"] for r in rows),
                # Counted per row, not as n - correct - refused. Those two are
                # not exclusive: an answer can hedge and still be right, and the
                # subtraction then reports a negative number of hallucinations.
                "grounded_invented": sum(
                    1 for r in rows
                    if not r["grounded"]["correct"] and not r["grounded"]["refused"]),
                "ungrounded_invented": sum(
                    1 for r in rows
                    if not r["ungrounded"]["correct"] and not r["ungrounded"]["refused"]),
                "bare_invented": sum(
                    1 for r in rows
                    if not r["bare"]["correct"] and not r["bare"]["refused"]),
                "grounded_output_tokens": sum(r["grounded"]["output_tokens"] for r in rows),
                "ungrounded_output_tokens": sum(r["ungrounded"]["output_tokens"] for r in rows),
                "n": n,
            },
        }
        print()

    (ROOT / "results" / "answers.json").write_text(json.dumps({
        "index": INDEX, "top_k": TOP_K,
        "system_grounded": SYSTEM, "system_ungrounded": SYSTEM_NO_RAG,
        "models": results,
    }, indent=2) + "\n")

    print(f"  {'model':18} {'arm':26} {'correct':>8} {'refused':>8} {'INVENTED':>9} {'out tok':>8}")
    print(f"  {'-'*18} {'-'*26} {'-'*8} {'-'*8} {'-'*9} {'-'*8}")
    for key, data in results.items():
        t = data["totals"]
        n = t["n"]
        arms = [
            ("RAG: sources + may refuse", "grounded"),
            ("no sources, may refuse", "ungrounded"),
            ("no sources, no permission", "bare"),
        ]
        for label, arm in arms:
            print(f"  {key:18} {label:26} {t[f'{arm}_correct']:>5}/{n} "
                  f"{t[f'{arm}_refused']:>5}/{n} {t[f'{arm}_invented']:>6}/{n} "
                  f"{t[f'{arm}_output_tokens']:>8}")
        print(f"  {'':18} {'cited a source':26} {t['grounded_cited']:>5}/{n} "
              f"{'':>5} {'':>6}  wrong-cite {t['cited_wrong_source']}")
        print()

    print("\n  written to results/answers.json")


if __name__ == "__main__":
    main()
