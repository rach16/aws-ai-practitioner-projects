# Model bench results

Generated 2026-10-16 17:51 UTC · region `us-east-1` · prices fetched 2026-10-16T16:37:22+00:00

8 models, 20 graded cases each, temperature pinned at 0.


## Overall

| Model | Score | Model latency | p95 | Round trip | Output tokens | This run | Per 10k | Price from |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `nova-micro` | 16/20 (80%) | 393 ms | 1112 ms | 557 ms | 1215 | $0.00020 | $0.10 | pricing-api |
| `nova-lite` | 17/20 (85%) | 347 ms | 560 ms | 480 ms | 705 | $0.00023 | $0.11 | pricing-api |
| `nova-pro` | 17/20 (85%) | 891 ms | 2337 ms | 997 ms | 1177 | $0.00453 | $2.27 | pricing-api |
| `claude-haiku-4.5` | 17/20 (85%) | 820 ms | 1730 ms | 969 ms | 902 | $0.00564 | $2.82 | manual |
| `llama3-8b` | 16/20 (80%) | 547 ms | 1876 ms | 653 ms | 804 | $0.00084 | $0.42 | pricing-api |
| `llama3.3-70b` | 17/20 (85%) | 632 ms | 1805 ms | 733 ms | 739 | $0.00169 | $0.85 | pricing-api |
| `mistral-7b` | 9/20 (45%) | 610 ms | 2282 ms | 715 ms | 905 | $0.00037 | $0.18 | pricing-api |
| `gpt-oss-20b` | 16/20 (80%) | 934 ms | 3005 ms | 1050 ms | 3448 | $0.00120 | $0.60 | pricing-api |

**Model latency** is what Bedrock reports it spent, and is the fair basis for comparing models. **Round trip** is what this machine measured, including credential resolution, TLS and network. The gap is client-side and is not the model's fault: an early version of this report quoted only the round trip, which on the first call through a fresh client was 2570 ms against the model's actual 231 ms.

`Per 10k` projects this run's measured token usage. `This run` is what the twenty calls actually cost.


## By task family

Deliberately not averaged into one number: these measure different abilities, and the right model depends on which column describes your workload.

| Model | Ticket sentiment classification | Structured extraction to JSON | Length-constrained summary | Literal instruction following | Multi-step arithmetic reasoning |
|---|---|---|---|---|---|
| `nova-micro` | 83% | 75% | 100% | 100% | 33% |
| `nova-lite` | 83% | 75% | 100% | 100% | 67% |
| `nova-pro` | 83% | 75% | 100% | 100% | 67% |
| `claude-haiku-4.5` | 67% | 100% | 67% | 100% | 100% |
| `llama3-8b` | 100% | 50% | 100% | 100% | 33% |
| `llama3.3-70b` | 67% | 75% | 100% | 100% | 100% |
| `mistral-7b` | 67% | 25% | 33% | 75% | 0% |
| `gpt-oss-20b` | 83% | 75% | 67% | 100% | 67% |

## Known measurement problems

**Contested answer keys.** These cases are kept in the suite and counted, but the key is arguable, so a model marked wrong here may not be wrong.

- `classify/c4` — Mixed sentiment: the problem was resolved but the experience was bad. The label set offers no 'mixed' option, so a model answering 'neutral' is making a defensible reading rather than an error. Kept in the suite and flagged in the report instead of being quietly rewritten, because a model scored wrong by an arguable answer key is a measurement failure, not a model weakness, and the difference is the thing worth being able to spot.
  > It works now, though I did lose an afternoon to it before support got back to me.

**Truncated answers.** These hit the `maxTokens` ceiling, so the ceiling was measured rather than the model. Treat the affected scores as a floor.

- `mistral-7b` — 2 of 20 responses cut off
- `gpt-oss-20b` — 1 of 20 responses cut off

**Hand-entered prices.** The AWS Pricing API publishes no us-east-1 on-demand token rate for these, so the figure was copied from the public pricing page on the date shown and is not machine-verified.

- `claude-haiku-4.5` — $1.00/1M in, $5.00/1M out, checked 2026-10-16, from https://aws.amazon.com/bedrock/pricing/ (Anthropic tab)


## Temperature

Prompt: *Invent a name for a coffee shop. Reply with the name only.* · 5 repeats per setting · the number is how many **distinct** answers came back.

| Model | temp 0.0 | temp 1.0 |
|---|---|---|
| `nova-micro` | 1 | 4 |
| `nova-lite` | 1 | 4 |
| `nova-pro` | 1 | 4 |
| `claude-haiku-4.5` | 1 | 5 |
| `llama3-8b` | 1 | 4 |
| `llama3.3-70b` | 1 | 1 |
| `mistral-7b` | 1 | 4 |
| `gpt-oss-20b` | 2 | 5 |

One distinct answer at temperature 0 is the expected result and is what makes the graded run above reproducible. More than one at temperature 1 shows the sampler doing its job.

### Temperature 0 is not deterministic on every model

These returned more than one distinct answer at temperature 0, which is the setting the graded run above relies on for reproducibility:

- **`gpt-oss-20b`** — 2 distinct answers in 5 calls: ['Bean & Quill', 'Roast & Reverie', 'Bean & Quill', 'Roast & Reverie', 'Bean & Quill']

Temperature 0 means greedy decoding, always take the highest-probability token. It does not mean the same answer every time, because on a distributed serving stack the ranking of two near-equal tokens can depend on batching, hardware and floating point order. The guarantee is about the sampler, not about the infrastructure under it.

The practical consequence for this report: any score for the models listed above is one sample, not a fixed value, and re-running the suite will move it. A sound comparison would run those models several times and report a range. This run does not, and the single number should be read with that in mind.

