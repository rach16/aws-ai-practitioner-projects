# P1 · Model Bench

Same twenty questions, every model, measured. Which Bedrock model should you
actually pick, and what does the choice cost?

Everyone agrees the answer depends on cost, latency and quality. This measures
all three instead of asserting it, and the interesting part turned out to be how
easy it is to measure them wrong.

**[Full results →](results/REPORT.md)** · **[Why it was built this way →](DECISIONS.md)**
· **[Cleanup →](TEARDOWN.md)**

## Results

Seven models, twenty graded cases each, temperature pinned at 0, us-east-1.

| Model | Score | Mean latency | Per 10k requests |
|---|---:|---:|---:|
| `nova-micro` | 17/20 (85%) | 533 ms | **$0.10** |
| `llama3.3-70b` | 17/20 (85%) | 617 ms | $0.88 |
| `nova-lite` | 16/20 (80%) | 491 ms | $0.12 |
| `nova-pro` | 16/20 (80%) | 826 ms | $1.88 |
| `llama3-8b` | 16/20 (80%) | 615 ms | $0.42 |
| `gpt-oss-20b` | 14/20 (70%) | 907 ms | $0.62 |
| `mistral-7b` | 9/20 (45%) | 631 ms | $0.18 |

`Per 10k requests` projects this run's measured token usage. The run itself cost
under two cents in total.

**Nova Micro ties for the best score at a nineteenth of Nova Pro's cost and two
thirds of its latency.** On this workload the expensive model is strictly worse:
same answers, slower, nineteen times the bill. That is the finding, and it is
the opposite of what picking by tier would have told you.

The caveat that makes it honest: twenty cases is a small sample, and 17/20
against 16/20 is one question. The gap that is real is the price column, where
Nova Pro costs 19× more without winning a single family outright.

### It depends which job you mean

Never averaged into a single score, because the families measure different
things:

| Model | Classify | JSON | Summarise | Instructions | Arithmetic |
|---|---|---|---|---|---|
| `nova-micro` | 83% | 100% | 100% | 100% | 33% |
| `nova-lite` | 83% | 75% | 67% | 100% | 67% |
| `nova-pro` | 67% | 75% | 100% | 100% | 67% |
| `llama3-8b` | 100% | 50% | 100% | 100% | 33% |
| `llama3.3-70b` | 67% | 75% | 100% | 100% | **100%** |
| `mistral-7b` | 67% | 25% | 33% | 75% | 0% |
| `gpt-oss-20b` | 83% | 75% | 33% | 75% | 67% |

Nova Micro is perfect at JSON extraction and fails two thirds of the arithmetic.
Llama 3.3 70B is the only model to sweep the reasoning column. If your workload
is extraction, the cheapest model on the list is also the best one; if it is
multi-step reasoning, it is the worst. A single headline number would have
hidden both facts.

## What the suite measures

Twenty cases in five families, every one graded by code. No human and no
LLM-as-judge, so the same run grades the same way every time.

| Family | Task | Scored by |
|---|---|---|
| `classify` | Sentiment of support tickets, 3 labels | Exact match |
| `extract` | Order text → strict JSON | Parses, and fields match |
| `constrain` | Summarise in ≤20 words | Word count, plus a required term so silence cannot win |
| `instruct` | "Answer with the bare value only" | Exact match after normalising |
| `reason` | Multi-step arithmetic | Final number, with tolerance |

Plus a temperature sweep: one prompt, two settings, five repeats, counting
distinct answers.

## Three bugs worth more than the results

**A model scored 20% when the right answer was 80%.** `gpt-oss-20b` is a
reasoning model: it spends output tokens thinking before it answers. The suite
gave classification questions a 10-token ceiling, which is plenty for the word
"negative" and nothing like enough for reasoning plus the word "negative". Every
short answer came back as an empty string and scored zero. With a per-model
512-token floor it scores 80%. **The harness was wrong by sixty percentage
points and the number looked entirely plausible.**

**Temperature 0 is not deterministic on every model.** `gpt-oss-20b` returned
four distinct answers in five calls at temperature 0, while every other model
returned one. Greedy decoding picks the highest-probability token, but on a
distributed serving stack the ranking of two near-equal tokens can shift with
batching and floating point order. It is also the only model whose score moved
between two identical runs, 80% then 70%. Its number is a sample, not a value.

**A contested answer key was kept rather than quietly fixed.** One ticket reads
*"It works now, though I did lose an afternoon to it before support got back to
me."* The key says `negative`; Nova Micro and Nova Pro independently say
`neutral`, and the three available labels contain no `mixed`. The case stays in,
counted against the models, flagged in the report. A benchmark where nothing is
contested means nobody read their own results.

The common thread: **a benchmark number is a claim about the measuring
apparatus at least as much as about the model**, and a wrong one does not
announce itself. Every one of these produced a plausible-looking table.

## Not measured

`claude-haiku-4.5` is in the lineup and has no results. Every call returns
`ResourceNotFoundException: Model use case details have not been submitted for
this account`. The Anthropic use case form is an account-level gate, separate
from granting model access, and it is not filled in. The row is left in the
report as an error rather than dropped, because a lineup that silently omits
what did not work is not a lineup.

It is also the one model priced by hand. The AWS Pricing API publishes no
us-east-1 on-demand token rate for any current Anthropic model, only the legacy
Claude 2.x and Claude 3 entries, so its price is copied from the public pricing
page with the date it was checked and marked `manual` in the report. Every other
price is fetched live.

## Running it

Needs an AWS profile named `personal` with Bedrock access in us-east-1.

```bash
python -m venv .venv && ./.venv/bin/pip install -r p1-model-bench/requirements.txt
cd p1-model-bench

python -m bench.pricing              # fetch live token prices -> config/pricing.json
python -m bench.run                  # graded suite -> results/raw.jsonl
python -m bench.run --sweep          # temperature sweep
python -m bench.report               # -> results/REPORT.md and results/results.csv
```

`--only nova-micro,nova-lite` re-runs a subset and merges into the existing
results rather than replacing them.

A full eight-model run is about 210 API calls and costs under two cents. Nothing
here bills while idle: no endpoints, no Provisioned Throughput, no vector store.
See [TEARDOWN.md](TEARDOWN.md).

## Exam domains

Domain 2 (Fundamentals of Generative AI) and Domain 3 (Applications of
Foundation Models): model selection criteria, inference parameters, token-based
pricing, the Converse API, cross-region inference profiles, and evaluating model
performance against a defined task.
