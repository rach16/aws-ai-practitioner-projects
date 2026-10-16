# Model bench results

Generated 2026-10-16 17:04 UTC · region `us-east-1` · prices fetched 2026-10-16T16:37:22+00:00

8 models, 20 graded cases each, temperature pinned at 0.


## Overall

| Model | Score | Mean latency | p95 | Output tokens | This run | Per 10k requests | Price from |
|---|---:|---:|---:|---:|---:|---:|---|
| `nova-micro` | 17/20 (85%) | 533 ms | 1429 ms | 1185 | $0.00020 | $0.10 | pricing-api |
| `nova-lite` | 16/20 (80%) | 491 ms | 650 ms | 763 | $0.00024 | $0.12 | pricing-api |
| `nova-pro` | 16/20 (80%) | 826 ms | 1996 ms | 936 | $0.00376 | $1.88 | pricing-api |
| `claude-haiku-4.5` | 0/20 (0%) | -- ms | -- ms | 0 | $0.00000 | $0.00 | manual |
| `llama3-8b` | 16/20 (80%) | 615 ms | 1947 ms | 804 | $0.00084 | $0.42 | pricing-api |
| `llama3.3-70b` | 17/20 (85%) | 617 ms | 1876 ms | 827 | $0.00176 | $0.88 | pricing-api |
| `mistral-7b` | 9/20 (45%) | 631 ms | 1778 ms | 905 | $0.00037 | $0.18 | pricing-api |
| `gpt-oss-20b` | 14/20 (70%) | 907 ms | 3375 ms | 3585 | $0.00124 | $0.62 | pricing-api |

`Per 10k requests` is a projection from this run's measured token usage, not money spent. `This run` is what the twenty calls actually cost.


## By task family

Deliberately not averaged into one number: these measure different abilities, and the right model depends on which column describes your workload.

| Model | Ticket sentiment classification | Structured extraction to JSON | Length-constrained summary | Literal instruction following | Multi-step arithmetic reasoning |
|---|---|---|---|---|---|
| `nova-micro` | 83% | 100% | 100% | 100% | 33% |
| `nova-lite` | 83% | 75% | 67% | 100% | 67% |
| `nova-pro` | 67% | 75% | 100% | 100% | 67% |
| `claude-haiku-4.5` | 0% | 0% | 0% | 0% | 0% |
| `llama3-8b` | 100% | 50% | 100% | 100% | 33% |
| `llama3.3-70b` | 67% | 75% | 100% | 100% | 100% |
| `mistral-7b` | 67% | 25% | 33% | 75% | 0% |
| `gpt-oss-20b` | 83% | 75% | 33% | 75% | 67% |

## Known measurement problems

**Contested answer keys.** These cases are kept in the suite and counted, but the key is arguable, so a model marked wrong here may not be wrong.

- `classify/c4` — Mixed sentiment: the problem was resolved but the experience was bad. The label set offers no 'mixed' option, so a model answering 'neutral' is making a defensible reading rather than an error. Kept in the suite and flagged in the report instead of being quietly rewritten, because a model scored wrong by an arguable answer key is a measurement failure, not a model weakness, and the difference is the thing worth being able to spot.
  > It works now, though I did lose an afternoon to it before support got back to me.

**Truncated answers.** These hit the `maxTokens` ceiling, so the ceiling was measured rather than the model. Treat the affected scores as a floor.

- `mistral-7b` — 2 of 20 responses cut off
- `gpt-oss-20b` — 1 of 20 responses cut off

**API errors.**

- `claude-haiku-4.5` — 20 failed: ResourceNotFoundException: Model use case details have not been submitted for this account. Fill out the Anthropic use case details form before using the model. If you have already filled out the form

**Hand-entered prices.** The AWS Pricing API publishes no us-east-1 on-demand token rate for these, so the figure was copied from the public pricing page on the date shown and is not machine-verified.

- `claude-haiku-4.5` — $1.00/1M in, $5.00/1M out, checked 2026-10-16, from https://aws.amazon.com/bedrock/pricing/ (Anthropic tab)


## Temperature

Prompt: *Invent a name for a coffee shop. Reply with the name only.* · 5 repeats per setting · the number is how many **distinct** answers came back.

| Model | temp 0.0 | temp 1.0 |
|---|---|---|
| `nova-micro` | 1 | 4 |
| `nova-lite` | 1 | 5 |
| `nova-pro` | 1 | 4 |
| `claude-haiku-4.5` | not measured | not measured |
| `llama3-8b` | 1 | 4 |
| `llama3.3-70b` | 1 | 2 |
| `mistral-7b` | 1 | 3 |
| `gpt-oss-20b` | 4 | 4 |

One distinct answer at temperature 0 is the expected result and is what makes the graded run above reproducible. More than one at temperature 1 shows the sampler doing its job.

### Temperature 0 is not deterministic on every model

These returned more than one distinct answer at temperature 0, which is the setting the graded run above relies on for reproducibility:

- **`gpt-oss-20b`** — 4 distinct answers in 5 calls: ['Roast & Reverie', 'Perk & Ponder', 'Roast & Reverie', 'Caffeine Canvas', 'Bean & Quill']

Temperature 0 means greedy decoding, always take the highest-probability token. It does not mean the same answer every time, because on a distributed serving stack the ranking of two near-equal tokens can depend on batching, hardware and floating point order. The guarantee is about the sampler, not about the infrastructure under it.

The practical consequence for this report: any score for the models listed above is one sample, not a fixed value, and re-running the suite will move it. A sound comparison would run those models several times and report a range. This run does not, and the single number should be read with that in mind.

