"""Run every task case against every model and record what happened.

Uses the Converse API rather than InvokeModel. Both reach the same models, but
InvokeModel takes a request body in each provider's own schema -- Anthropic,
Meta and Mistral all shape their JSON differently -- so a benchmark built on it
spends most of its code translating. Converse takes one shape for all of them
and returns token counts in a consistent place, which is the only reason a
lineup this mixed fits in one loop.

Not every model accepts every part of that shape. Mistral 7B on Bedrock rejects
a separate system block, so when that happens the system text is folded into the
user turn and the fallback is recorded on the row rather than hidden, because a
model that needed the workaround was not asked quite the same question as the
rest.

Temperature is pinned at 0 for the graded run so the scores reflect the model
and not the sampler. The separate --sweep mode is where temperature is allowed
to vary, on purpose.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import bench._path  # noqa: F401  -- puts the repo root on sys.path for shared/
from bench.tasks import iter_cases, load_tasks, score
from shared.bedrock import client as bedrock_client
from shared.bedrock import converse as bedrock_converse

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
RESULTS = ROOT / "results"


def load_models() -> dict:
    return json.loads((CONFIG / "models.json").read_text())


def run_suite(models: dict, tasks: dict, out_path: Path) -> int:
    client = bedrock_client(region=models["region"])
    cases = list(iter_cases(tasks))
    rows = []

    for model in models["models"]:
        key, model_id = model["key"], model["model_id"]
        print(f"\n{key}  ({model_id})")
        for family, case in cases:
            # Reasoning models spend output tokens before they say anything, so a
            # per-model floor keeps the suite from grading an empty string.
            max_tokens = max(family["max_tokens"], model.get("max_tokens_floor", 0))

            response = bedrock_converse(
                client, model_id, case["prompt"],
                system=family.get("system", ""),
                max_tokens=max_tokens,
                temperature=0.0,
            )
            result = response.as_dict()

            row = {
                "model": key,
                "model_id": model_id,
                "family": family["id"],
                "case": case["id"],
                **result,
            }

            if "error" in result:
                row["passed"] = False
                row["reason"] = result["error"]
                print(f"  {family['id']:10} {case['id']:4} ERROR  {result['error'][:70]}")
            else:
                passed, reason = score(family, case, result["text"])
                row["passed"] = passed
                row["reason"] = reason
                mark = "ok  " if passed else "MISS"
                print(f"  {family['id']:10} {case['id']:4} {mark} "
                      f"{result['server_latency_ms'] or result['latency_ms']:6.0f}ms  "
                      f"{result['input_tokens']:4}in/{result['output_tokens']:4}out  {reason[:50]}")

            rows.append(row)

    # Merge rather than overwrite, so re-running one model with --only replaces
    # just that model's rows and leaves the rest of the suite intact. Overwriting
    # here silently destroyed seven models' results the first time --only was used.
    existing = []
    if out_path.exists():
        rerun = {row["model"] for row in rows}
        with out_path.open() as handle:
            existing = [json.loads(line) for line in handle
                        if line.strip() and json.loads(line)["model"] not in rerun]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as handle:
        for row in existing + rows:
            handle.write(json.dumps(row) + "\n")

    kept = f", {len(existing)} kept from earlier runs" if existing else ""
    print(f"\n{len(rows)} rows written to {out_path.name}{kept}")
    return len(rows)


def run_sweep(models: dict, tasks: dict, out_path: Path) -> None:
    """Same prompt, two temperatures, several repeats. Counts distinct answers.

    This is the whole of the temperature concept in one measurable form: at
    temperature 0 a model should give the same answer every time, and above 0 it
    should not. Models that return one distinct answer at both settings are
    worth noticing -- it usually means the question had an overwhelmingly likely
    answer, not that the parameter was ignored.
    """
    config = tasks["temperature_sweep"]
    client = bedrock_client(region=models["region"])
    sweep = {}

    for model in models["models"]:
        key = model["key"]
        sweep[key] = {}
        for temperature in config["temperatures"]:
            answers = []
            for _ in range(config["repeats"]):
                response = bedrock_converse(
                    client, model["model_id"], config["prompt"],
                    max_tokens=config["max_tokens"],
                    temperature=temperature,
                )
                answers.append(response.text.strip() if response.ok
                               else f"ERROR {response.error}")
            sweep[key][str(temperature)] = {
                "answers": answers,
                "distinct": len(set(a.lower() for a in answers)),
            }
            print(f"{key:20} temp={temperature}  distinct={len(set(a.lower() for a in answers))}  {answers}")

    out_path.write_text(json.dumps({
        "prompt": config["prompt"],
        "repeats": config["repeats"],
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": sweep,
    }, indent=2) + "\n")
    print(f"\nwritten to {out_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Bedrock models on a fixed task suite.")
    parser.add_argument("--sweep", action="store_true",
                        help="run the temperature sweep instead of the graded suite")
    parser.add_argument("--only", help="comma-separated model keys, to re-run a subset")
    args = parser.parse_args()

    models = load_models()
    tasks = load_tasks()

    if args.only:
        wanted = {k.strip() for k in args.only.split(",")}
        models["models"] = [m for m in models["models"] if m["key"] in wanted]
        if not models["models"]:
            raise SystemExit(f"no models matched {sorted(wanted)}")

    RESULTS.mkdir(exist_ok=True)
    if args.sweep:
        run_sweep(models, tasks, RESULTS / "temperature-sweep.json")
    else:
        run_suite(models, tasks, RESULTS / "raw.jsonl")


if __name__ == "__main__":
    main()
