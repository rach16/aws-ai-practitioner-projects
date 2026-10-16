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

| Model | Score | Model latency | Per 10k requests |
|---|---:|---:|---:|
| `nova-lite` | 17/20 (85%) | **347 ms** | **$0.11** |
| `nova-pro` | 17/20 (85%) | 891 ms | $2.27 |
| `llama3.3-70b` | 17/20 (85%) | 632 ms | $0.85 |
| `nova-micro` | 16/20 (80%) | 393 ms | $0.10 |
| `llama3-8b` | 16/20 (80%) | 547 ms | $0.42 |
| `gpt-oss-20b` | 16/20 (80%) | 934 ms | $0.60 |
| `mistral-7b` | 9/20 (45%) | 610 ms | $0.18 |

**Nova Lite matches Nova Pro's score at a twentieth of the cost and two and a
half times the speed.** Same twenty questions, same number right, $0.11 against
$2.27 per ten thousand requests. On this workload the expensive tier buys
nothing.

That is the finding, and it is the opposite of what picking by tier would say.

### The scores are samples, not values

The suite was run twice, identically. Four of the seven models moved:

| Model | Run 1 | Run 2 |
|---|---:|---:|
| `nova-micro` | 17/20 | 16/20 |
| `nova-lite` | 16/20 | 17/20 |
| `nova-pro` | 16/20 | 17/20 |
| `gpt-oss-20b` | 14/20 | 16/20 |
| `llama3-8b` | 16/20 | 16/20 |
| `llama3.3-70b` | 17/20 | 17/20 |
| `mistral-7b` | 9/20 | 9/20 |

Temperature was 0 in both. The separate temperature sweep shows every model
except `gpt-oss-20b` returning one identical answer five times out of five at
temperature 0, so this is not the sampler. Determinism on one short prompt does
not carry to twenty longer ones: a tiny difference in token ranking early in a
generation changes everything after it, and several cases sit right on a
scoring boundary, a summary at exactly twenty words or an arithmetic answer one
step from correct.

**So a one-point gap between models here is noise.** 17/20 against 16/20 says
nothing. What survives the variance is the cost column, where Nova Pro is 20×
Nova Lite and never once scores higher, and `mistral-7b` at 45% is not a
sampling artefact.

The right fix is several runs per model reported as a range. This repository
has two, which is enough to know the single number was misleading and not
enough to replace it. Stated rather than smoothed over.

### It depends which job you mean

Never averaged into a single score, because the families measure different
things:

| Model | Classify | JSON | Summarise | Instructions | Arithmetic |
|---|---|---|---|---|---|
| `nova-micro` | 83% | 100% | 67% | 100% | 33% |
| `nova-lite` | 83% | 75% | 100% | 100% | 67% |
| `nova-pro` | 83% | 75% | 100% | 100% | 67% |
| `llama3-8b` | 100% | 50% | 100% | 100% | 33% |
| `llama3.3-70b` | 67% | 75% | 100% | 100% | **100%** |
| `mistral-7b` | 67% | 25% | 33% | 75% | 0% |
| `gpt-oss-20b` | 83% | 75% | 67% | 75% | 100% |

Llama 3.3 70B is the only model to sweep the arithmetic column; Nova Micro
fails two thirds of it while scoring 100% on JSON extraction. If your workload
is extraction, one of the cheapest models on the list is among the best; if it
is multi-step reasoning, it is the worst. A single headline number hides both.

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

## Four bugs worth more than the results

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

**Latency was being measured wrong, and the log proved it.** The report quoted
the round trip measured on this machine. With invocation logging switched on,
the same call appeared in CloudWatch reporting `latencyMs: 231` while the
client had recorded **2570 ms**. The missing 2.3 seconds was credential
resolution and the TLS handshake on a cold client, attributed to the model.
Both numbers are now recorded: what Bedrock spent, for comparing models, and
what the caller waited, for capacity planning. Neither is wrong; quoting only
one of them was.

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
this account`.

Worth knowing why that is a `ResourceNotFound` and not an access-denied: the
Bedrock **Model access page has been retired**. Serverless foundation models are
now enabled automatically on first invocation, so there is no access list to be
missing from. Two exceptions survive. Anthropic models still require use case
details from a first-time account, and Marketplace-served models need a user
with Marketplace permissions to invoke once. Until that clears, the model is
simply not resolvable for this account, which is what the error says.

The row is left in the report as an error rather than dropped, because a lineup
that silently omits what did not work is not a lineup.

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
