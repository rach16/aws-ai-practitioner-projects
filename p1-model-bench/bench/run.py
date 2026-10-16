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

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from bench.tasks import iter_cases, load_tasks, score

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
RESULTS = ROOT / "results"

MAX_ATTEMPTS = 5


def load_models() -> dict:
    return json.loads((CONFIG / "models.json").read_text())


def make_client(region: str):
    # Retries are handled in this module so that throttling delays never land in
    # the latency numbers; botocore's own retrying would hide them inside the call.
    return boto3.Session(profile_name="personal", region_name=region).client(
        "bedrock-runtime",
        config=Config(retries={"max_attempts": 1}, read_timeout=120),
    )


def converse(client, model_id: str, system: str, prompt: str, max_tokens: int,
             temperature: float) -> dict:
    """One graded call. Returns timing, token counts and the text, or an error."""
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    kwargs = {
        "modelId": model_id,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if system:
        kwargs["system"] = [{"text": system}]

    folded_system = False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            response = client.converse(**kwargs)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]

            # Fold the system prompt into the user turn for models that reject it.
            if code == "ValidationException" and "system" in kwargs and not folded_system:
                message = str(exc).lower()
                if "system" in message:
                    kwargs.pop("system")
                    kwargs["messages"] = [
                        {"role": "user", "content": [{"text": f"{system}\n\n{prompt}"}]}
                    ]
                    folded_system = True
                    continue

            if code in ("ThrottlingException", "ModelTimeoutException",
                        "ServiceUnavailableException", "InternalServerException"):
                if attempt < MAX_ATTEMPTS:
                    time.sleep(min(2 ** attempt, 20) + random.random())
                    continue

            return {"error": f"{code}: {exc.response['Error'].get('Message', '')[:200]}",
                    "attempts": attempt, "system_folded": folded_system}

        latency_ms = (time.perf_counter() - started) * 1000
        usage = response["usage"]
        text = "".join(
            block.get("text", "")
            for block in response["output"]["message"]["content"]
        )
        return {
            "text": text,
            "latency_ms": round(latency_ms, 1),
            "input_tokens": usage["inputTokens"],
            "output_tokens": usage["outputTokens"],
            "stop_reason": response.get("stopReason"),
            "attempts": attempt,
            "system_folded": folded_system,
        }

    return {"error": "exhausted retries", "attempts": MAX_ATTEMPTS,
            "system_folded": folded_system}


def run_suite(models: dict, tasks: dict, out_path: Path) -> int:
    client = make_client(models["region"])
    cases = list(iter_cases(tasks))
    rows = []

    for model in models["models"]:
        key, model_id = model["key"], model["model_id"]
        print(f"\n{key}  ({model_id})")
        for family, case in cases:
            # Reasoning models spend output tokens before they say anything, so a
            # per-model floor keeps the suite from grading an empty string.
            max_tokens = max(family["max_tokens"], model.get("max_tokens_floor", 0))

            result = converse(
                client, model_id,
                system=family.get("system", ""),
                prompt=case["prompt"],
                max_tokens=max_tokens,
                temperature=0.0,
            )

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
                      f"{result['latency_ms']:7.0f}ms  "
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
    client = make_client(models["region"])
    sweep = {}

    for model in models["models"]:
        key = model["key"]
        sweep[key] = {}
        for temperature in config["temperatures"]:
            answers = []
            for _ in range(config["repeats"]):
                result = converse(
                    client, model["model_id"], system="",
                    prompt=config["prompt"],
                    max_tokens=config["max_tokens"],
                    temperature=temperature,
                )
                answers.append(result.get("text", f"ERROR {result.get('error','')}").strip())
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
