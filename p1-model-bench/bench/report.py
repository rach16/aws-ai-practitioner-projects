"""Turn raw.jsonl into a report a reader can act on.

Three things this deliberately does not do.

It does not average the five task families into a single headline score. The
families measure different abilities and a mean over them would invent a
precision that is not there; a model that is perfect at classification and
hopeless at JSON is not "60% good". The families stay in separate columns so
the reader picks the one matching their workload.

It does not quote the cost of the run as though it were the number that
matters. A twenty-call run costs a fraction of a cent on every model here, so
at that size they all look free. Cost is projected to a fixed 10,000 requests,
where the differences are real, and the actual run cost is shown separately so
a forecast is never mistaken for an invoice.

It does not hide the broken rows. Truncated answers, API errors, hand-entered
prices and contested answer keys all get called out, because a benchmark whose
failures are invisible is just a number with good PR.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
RESULTS = ROOT / "results"

PROJECTION = 10_000  # requests, for the cost column


def load(path: Path):
    return json.loads(path.read_text())


def read_rows() -> list[dict]:
    with (RESULTS / "raw.jsonl").open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def summarise(rows: list[dict], models: dict, prices: dict) -> list[dict]:
    by_model = defaultdict(list)
    for row in rows:
        by_model[row["model"]].append(row)

    order = [m["key"] for m in models["models"]]
    summary = []

    for key in order:
        model_rows = by_model.get(key)
        if not model_rows:
            continue

        good = [r for r in model_rows if "error" not in r]
        errors = len(model_rows) - len(good)
        truncated = sum(1 for r in good if r.get("stop_reason") == "max_tokens")

        # Two different questions. Server latency is what the model spent and is
        # the fair basis for comparing models. Client latency is what a caller
        # waits for, and includes credential resolution, TLS and network, which
        # on a cold client is seconds and nothing to do with the model.
        latencies = [r["latency_ms"] for r in good]
        server_latencies = [r["server_latency_ms"] for r in good
                            if r.get("server_latency_ms") is not None]
        input_tokens = sum(r["input_tokens"] for r in good)
        output_tokens = sum(r["output_tokens"] for r in good)

        price = prices["prices"].get(key, {})
        rate_in = price.get("input_usd_per_1k")
        rate_out = price.get("output_usd_per_1k")

        if rate_in is None:
            run_cost = projected = None
        else:
            run_cost = (input_tokens / 1000) * rate_in + (output_tokens / 1000) * rate_out
            per_request = run_cost / len(good) if good else 0
            projected = per_request * PROJECTION

        entry = {
            "model": key,
            "model_id": next(m["model_id"] for m in models["models"] if m["key"] == key),
            "n": len(model_rows),
            "errors": errors,
            "truncated": truncated,
            "passed": sum(1 for r in model_rows if r["passed"]),
            "accuracy": sum(1 for r in model_rows if r["passed"]) / len(model_rows),
            "server_latency_mean_ms": (statistics.mean(server_latencies)
                                       if server_latencies else None),
            "server_latency_p95_ms": (sorted(server_latencies)[int(len(server_latencies) * 0.95) - 1]
                                      if len(server_latencies) >= 2
                                      else (server_latencies[0] if server_latencies else None)),
            "latency_mean_ms": statistics.mean(latencies) if latencies else None,
            "latency_p95_ms": (sorted(latencies)[int(len(latencies) * 0.95) - 1]
                               if len(latencies) >= 2 else (latencies[0] if latencies else None)),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "run_cost_usd": run_cost,
            "cost_per_10k_usd": projected,
            "price_source": price.get("source", "unknown"),
        }

        for family, family_rows in group_by_family(model_rows).items():
            entry[f"acc_{family}"] = sum(1 for r in family_rows if r["passed"]) / len(family_rows)

        summary.append(entry)

    return summary


def group_by_family(rows: list[dict]) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for row in rows:
        out[row["family"]].append(row)
    return out


def fmt(value, spec: str, dash: str = "--") -> str:
    return dash if value is None else format(value, spec)


def write_csv(summary: list[dict], families: list[str]) -> None:
    columns = (["model", "model_id", "n", "passed", "accuracy"]
               + [f"acc_{f}" for f in families]
               + ["server_latency_mean_ms", "server_latency_p95_ms",
                  "latency_mean_ms", "latency_p95_ms", "input_tokens", "output_tokens",
                  "run_cost_usd", "cost_per_10k_usd", "price_source", "errors", "truncated"])
    with (RESULTS / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in summary:
            writer.writerow(row)


def build_markdown(summary: list[dict], tasks: dict, prices: dict, rows: list[dict]) -> str:
    families = [f["id"] for f in tasks["families"]]
    labels = {f["id"]: f["label"] for f in tasks["families"]}
    out: list[str] = []
    add = out.append

    add("# Model bench results\n")
    add(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"region `{prices['region']}` · prices fetched {prices['fetched_at']}\n")
    add(f"{len(summary)} models, {sum(len(f['cases']) for f in tasks['families'])} graded cases each, "
        f"temperature pinned at 0.\n")

    # --- headline -----------------------------------------------------------
    add("\n## Overall\n")
    add("| Model | Score | Model latency | p95 | Round trip | Output tokens | This run | Per 10k | Price from |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for s in summary:
        add(f"| `{s['model']}` | {s['passed']}/{s['n']} ({s['accuracy']:.0%}) "
            f"| {fmt(s['server_latency_mean_ms'], '.0f')} ms "
            f"| {fmt(s['server_latency_p95_ms'], '.0f')} ms "
            f"| {fmt(s['latency_mean_ms'], '.0f')} ms "
            f"| {s['output_tokens']} "
            f"| ${fmt(s['run_cost_usd'], '.5f')} | ${fmt(s['cost_per_10k_usd'], '.2f')} "
            f"| {s['price_source']} |")

    add("\n**Model latency** is what Bedrock reports it spent, and is the fair basis for "
        "comparing models. **Round trip** is what this machine measured, including credential "
        "resolution, TLS and network. The gap is client-side and is not the model's fault: an "
        "early version of this report quoted only the round trip, which on the first call "
        "through a fresh client was 2570 ms against the model's actual 231 ms.\n")
    add("`Per 10k` projects this run's measured token usage. `This run` is what the twenty "
        "calls actually cost.\n")

    # --- per family ---------------------------------------------------------
    add("\n## By task family\n")
    add("Deliberately not averaged into one number: these measure different abilities, "
        "and the right model depends on which column describes your workload.\n")
    header = "| Model | " + " | ".join(f"{labels[f]}" for f in families) + " |"
    add(header)
    add("|---" * (len(families) + 1) + "|")
    for s in summary:
        cells = " | ".join(fmt(s.get(f"acc_{f}"), ".0%") for f in families)
        add(f"| `{s['model']}` | {cells} |")

    # --- measurement problems ----------------------------------------------
    add("\n## Known measurement problems\n")

    contested = [(f["id"], c) for f in tasks["families"] for c in f["cases"] if c.get("contested")]
    if contested:
        add("**Contested answer keys.** These cases are kept in the suite and counted, "
            "but the key is arguable, so a model marked wrong here may not be wrong.\n")
        for family_id, case in contested:
            add(f"- `{family_id}/{case['id']}` — {case['contested']}")
            add(f"  > {case['prompt']}")
        add("")

    truncations = [s for s in summary if s["truncated"]]
    if truncations:
        add("**Truncated answers.** These hit the `maxTokens` ceiling, so the ceiling was "
            "measured rather than the model. Treat the affected scores as a floor.\n")
        for s in truncations:
            add(f"- `{s['model']}` — {s['truncated']} of {s['n']} responses cut off")
        add("")

    failures = [s for s in summary if s["errors"]]
    if failures:
        add("**API errors.**\n")
        for s in failures:
            reasons = {r["reason"] for r in rows if r["model"] == s["model"] and "error" in r}
            add(f"- `{s['model']}` — {s['errors']} failed: {'; '.join(sorted(reasons))[:200]}")
        add("")

    manual = [k for k, v in prices["prices"].items() if v.get("source") == "manual"]
    if manual:
        add("**Hand-entered prices.** The AWS Pricing API publishes no us-east-1 on-demand token "
            "rate for these, so the figure was copied from the public pricing page on the date "
            "shown and is not machine-verified.\n")
        for key in manual:
            price = prices["prices"][key]
            add(f"- `{key}` — ${price['input_usd_per_1k'] * 1000:.2f}/1M in, "
                f"${price['output_usd_per_1k'] * 1000:.2f}/1M out, "
                f"checked {price['checked']}, from {price['source_detail']}")
        add("")

    # --- temperature --------------------------------------------------------
    sweep_file = RESULTS / "temperature-sweep.json"
    if sweep_file.exists():
        sweep = load(sweep_file)
        add("\n## Temperature\n")
        add(f"Prompt: *{sweep['prompt']}* · {sweep['repeats']} repeats per setting · "
            "the number is how many **distinct** answers came back.\n")
        temps = sorted({t for v in sweep["results"].values() for t in v})
        add("| Model | " + " | ".join(f"temp {t}" for t in temps) + " |")
        add("|---" * (len(temps) + 1) + "|")

        nondeterministic = []
        for key, result in sweep["results"].items():
            # A model whose every reply was an API error has not been measured;
            # reporting "1 distinct" there would read as perfect determinism.
            if all(a.startswith("ERROR") for a in result[temps[0]]["answers"]):
                add(f"| `{key}` | " + " | ".join("not measured" for _ in temps) + " |")
                continue
            cells = " | ".join(str(result[t]["distinct"]) for t in temps)
            add(f"| `{key}` | {cells} |")
            if result["0.0"]["distinct"] > 1:
                nondeterministic.append((key, result["0.0"]))

        add("\nOne distinct answer at temperature 0 is the expected result and is what makes the "
            "graded run above reproducible. More than one at temperature 1 shows the sampler "
            "doing its job.\n")

        if nondeterministic:
            add("### Temperature 0 is not deterministic on every model\n")
            add("These returned more than one distinct answer at temperature 0, which is the "
                "setting the graded run above relies on for reproducibility:\n")
            for key, result in nondeterministic:
                add(f"- **`{key}`** — {result['distinct']} distinct answers in "
                    f"{len(result['answers'])} calls: {result['answers']}")
            add("")
            add("Temperature 0 means greedy decoding, always take the highest-probability "
                "token. It does not mean the same answer every time, because on a distributed "
                "serving stack the ranking of two near-equal tokens can depend on batching, "
                "hardware and floating point order. The guarantee is about the sampler, not "
                "about the infrastructure under it.\n")
            add("The practical consequence for this report: any score for the models listed "
                "above is one sample, not a fixed value, and re-running the suite will move it. "
                "A sound comparison would run those models several times and report a range. "
                "This run does not, and the single number should be read with that in mind.\n")

    return "\n".join(out) + "\n"


def main() -> None:
    models = load(CONFIG / "models.json")
    tasks = load(CONFIG / "tasks.json")
    prices = load(CONFIG / "pricing.json")
    rows = read_rows()

    summary = summarise(rows, models, prices)
    write_csv(summary, [f["id"] for f in tasks["families"]])
    (RESULTS / "REPORT.md").write_text(build_markdown(summary, tasks, prices, rows))

    print(f"{len(rows)} rows -> {len(summary)} models")
    print(f"wrote results/results.csv and results/REPORT.md")


if __name__ == "__main__":
    main()
