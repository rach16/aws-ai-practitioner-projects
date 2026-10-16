# P1 · Model Bench

Same twenty questions, every model, measured. Which Bedrock model should you
actually pick, and what does the choice cost?

Everyone agrees the answer depends on cost, latency and quality. This measures
all three instead of asserting it, and the interesting part turned out to be how
easy it is to measure them wrong.

**[Full results →](results/REPORT.md)** · **[Why it was built this way →](DECISIONS.md)**
· **[Cleanup →](TEARDOWN.md)**

## Results

Eight models, twenty graded cases each, temperature pinned at 0, us-east-1.

| Model | Score | Model latency | Per 10k requests |
|---|---:|---:|---:|
| `nova-lite` | 17/20 (85%) | **347 ms** | **$0.11** |
| `llama3.3-70b` | 17/20 (85%) | 632 ms | $0.85 |
| `nova-pro` | 17/20 (85%) | 891 ms | $2.27 |
| `claude-haiku-4.5` | 17/20 (85%) | 820 ms | $2.82 |
| `nova-micro` | 16/20 (80%) | 393 ms | $0.10 |
| `llama3-8b` | 16/20 (80%) | 547 ms | $0.42 |
| `gpt-oss-20b` | 16/20 (80%) | 934 ms | $0.60 |
| `mistral-7b` | 9/20 (45%) | 610 ms | $0.18 |

**Four models tie at 85%. They cost $0.11, $0.85, $2.27 and $2.82 per ten
thousand requests.** A 26× price spread across models that answered the same
number of questions correctly, with the cheapest also the fastest.

That is the finding, and it is the opposite of what picking by tier or by brand
would tell you. On this workload, paying more bought nothing.

What it does not say is that Nova Lite is the best model. It says the twenty
questions in this suite do not distinguish the top four, which is a fact about
the suite as much as about the models. A harder suite would separate them. The
honest claim is narrower and more useful: **if your task looks like these
twenty, the expensive options are wasted money, and you should find that out by
measuring rather than by reading a tier list.**

### The scores are samples, not values

The suite was run twice, identically. Four of the seven models moved:

Anthropic was still blocked during these two runs, so it has one run only.

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
| `nova-micro` | 83% | 75% | 100% | 100% | 33% |
| `nova-lite` | 83% | 75% | 100% | 100% | 67% |
| `nova-pro` | 83% | 75% | 100% | 100% | 67% |
| `claude-haiku-4.5` | 67% | **100%** | 67% | 100% | **100%** |
| `llama3-8b` | **100%** | 50% | 100% | 100% | 33% |
| `llama3.3-70b` | 67% | 75% | 100% | 100% | **100%** |
| `mistral-7b` | 67% | 25% | 33% | 75% | 0% |
| `gpt-oss-20b` | 83% | 75% | 67% | 100% | 67% |

**This is where the four-way tie comes apart.** Claude Haiku is the only model
to take both JSON extraction and arithmetic outright, and Llama 3.3 70B is the
only other model to sweep arithmetic. Nova Lite, the cheapest of the four, is
behind on both and makes up the difference on summarising.

So the tie at 85% is four models being good at different things, not four
interchangeable models. If the workload is structured extraction or multi-step
reasoning, the 26× price gap starts to look like it buys something. If it is
classification and summarising, it does not.

Note also that Llama 3 8B tops the classification column outright while placing
second to last on JSON. A single averaged score would have ranked it mid-table
and told you nothing about either.

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

## The Anthropic gate

`claude-haiku-4.5` was 20 error rows for most of this project's life. Every
call returned `ResourceNotFoundException: Model use case details have not been
submitted for this account`.

Worth knowing why that is a `ResourceNotFound` rather than an access denial:
the Bedrock **Model access page has been retired**. Serverless foundation
models are now enabled automatically on first invocation, so there is no access
list to be missing from. Two exceptions survive. Anthropic models require
first-time use case details, submitted once per account, and the information
goes to Anthropic. Marketplace-served models need a user with Marketplace
permissions to invoke once. Until that clears the model is not resolvable for
the account at all, which is exactly what the error says.

Submitting the form took a few minutes and access was live immediately after,
not the fifteen minutes the error warns about.

It remains the one model priced by hand. The AWS Pricing API publishes no
us-east-1 on-demand token rate for any current Anthropic model, only the legacy
Claude 2.x and Claude 3 entries, so its $1.00/$5.00 per million is copied from
the public pricing page with the date checked, and the report marks that row
`manual` while every other row says `pricing-api`. It is also the most
expensive model in the lineup, which makes the distinction worth keeping
visible rather than quietly folding a typed number into a fetched table.

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
