# Decisions

What was chosen, what was rejected, and what went wrong on the way. Several of
these were forced by something breaking during the build rather than decided up
front, and those are the more useful ones.

## Converse API rather than InvokeModel

Both reach the same models. `InvokeModel` takes a request body in each
provider's own schema, so Anthropic, Meta and Mistral all want differently
shaped JSON and a benchmark built on it spends most of its code translating
between them. `Converse` takes one shape for every model and returns token
counts in a consistent place.

That is the only reason a lineup this mixed fits in one loop. The cost is that
`Converse` exposes the common subset of inference parameters, so a
provider-specific knob would need `additionalModelRequestFields`. Nothing here
needs one.

## Deterministic scoring, no LLM judge

Every case is graded by code: exact match, JSON field comparison, word count,
or numeric extraction. An LLM judge would be more forgiving about phrasing, and
would make the numbers unreproducible, because the grade would then depend on a
model's opinion on the day. A benchmark nobody can re-run is an anecdote.

The cost is real. Grading is strict, and some of what it marks wrong is the
model being differently right. `extract/e3` wants `"EUR"` and most models
answer `"euros"`, which is not a misunderstanding, it is a missing instruction
in my prompt. Both are recorded in the report rather than smoothed over.

## Prices fetched from the Pricing API, not hardcoded

Token prices change, and a number typed into a config file is wrong the moment
it changes without anyone noticing. `bench/pricing.py` pulls the live per-1,000
token rate for each model and writes `config/pricing.json`.

Two things made this messier than expected, and both are visible in the code:

**A model's pricing record is not keyed by its model ID.** `amazon.nova-micro-v1:0`
is billed under the usagetype `USE1-NovaMicro-input-tokens`. So each model
carries its usagetype prefix in `config/models.json` and the lookup is an exact
match, which also prevents the cheaper `-flex`, the dearer `-priority` and the
prompt-cache rates from being picked up by accident.

**Not every model is in the API.** No current Anthropic model has a published
us-east-1 on-demand rate; only the legacy Claude 2.x and Claude 3 entries are
there. Those models carry a `price_override` copied from the public pricing
page with the date it was checked, and the report marks those rows as
hand-entered. Quietly mixing a typed number in with fetched ones would make the
whole table look machine-verified when it is not.

## Cost is projected to 10,000 requests

A twenty-call run costs a fraction of a cent on every model in the lineup, so
at that size they are indistinguishable and the comparison says nothing. The
report projects measured token usage to a fixed 10,000 requests, where the
differences are real, and shows the actual run cost in a separate column so a
forecast is never read as an invoice.

## The five task families are never averaged

They measure different abilities. A model that is perfect at classification and
hopeless at JSON is not "60% good", and a single headline score would invent a
precision that is not there. The families stay in separate columns and the
reader picks the one that matches their workload.

## A contested answer key was kept rather than fixed

`classify/c4` is this ticket:

> It works now, though I did lose an afternoon to it before support got back to me.

The key says `negative`. Nova Micro and Nova Pro independently answer `neutral`,
and they have a case: the sentiment is genuinely mixed, the outcome was good and
the experience was bad, and the three available labels contain no `mixed`.

The obvious move is to rewrite the case so the score comes out clean. It is kept
instead, flagged in the report with the reasoning, and counted against the
models. A benchmark where nothing is contested means nobody looked hard at the
results. The difference between a model being wrong and a measurement being
wrong is the thing this project is supposed to be able to tell, so hiding the
one example of it would be the wrong trade.

## A per-model token floor, after an 80% error

`gpt-oss-20b` first scored 20%. Every short answer came back as an empty string,
truncated at the ceiling.

It is a reasoning model: it emits an internal reasoning block before the answer,
and that block is billed and counted as output. The suite gives classification
questions a 10-token ceiling, which is ample for the word "negative" and nowhere
near enough for reasoning plus the word "negative". The model was scored zero on
questions it was never given room to answer.

With a 512-token floor it scores 80%. **The harness was wrong by sixty
percentage points and the number looked perfectly plausible.** That is the most
useful thing this project produced: a benchmark result is a claim about the
measurement apparatus at least as much as about the model, and a wrong one does
not announce itself.

The floor is per-model rather than global because raising the ceiling for
everyone would let verbose models inflate their own cost. It does make
`gpt-oss-20b` look expensive in the cost column, which is accurate: those
reasoning tokens are billed, and that genuinely is what the model costs to use.

The report now flags any row that stopped on `max_tokens`, so the next instance
of this is visible rather than silent.

## Both latencies are recorded, because they answer different questions

The first version timed the round trip on this machine and called it latency.
Switching on model invocation logging exposed the problem immediately: the same
call appeared in CloudWatch reporting `latencyMs: 231` while the client had
measured 2570 ms. The gap was credential resolution and the TLS handshake on a
cold client, and it was being reported as though the model were slow.

Both are now recorded. Server-reported latency is the fair basis for comparing
models, because it is the part the model is responsible for. Client-measured
round trip is what a caller actually waits for, and is the number that matters
for capacity planning. Publishing one without the other invites the reader to
use it for the wrong question.

The general lesson is the reason the logging was worth turning on at all: the
service's own telemetry is a check on your instrumentation, and here it caught
an error of an order of magnitude.

## Temperature pinned at 0 for grading, swept separately

The graded run pins temperature at 0 so scores reflect the model and not the
sampler. Temperature gets its own mode, `--sweep`, which sends one prompt
repeatedly at two settings and counts distinct answers.

The first sweep prompt was "Name a colour." Nearly every model answered "Blue"
five times out of five at temperature 1, which made it look as though the models
ignored the parameter. They did not: temperature rescales the probability
distribution rather than flattening it, and "name a colour" has one
overwhelmingly likely completion for it to act on. The prompt is now an invented
coffee shop name, which has many plausible answers. A bad probe reads exactly
like a negative result, which is the same lesson as the `gpt-oss-20b` one.

## `--only` merges instead of overwriting

The first version rewrote `results/raw.jsonl` from scratch on every run, so
re-running one model with `--only` destroyed the other seven models' results.
It now reads the existing file, drops the rows for the models being re-run, and
writes the rest back. Re-running one model after fixing its configuration is the
normal case, not the exception.

## Nothing here bills while idle

Bedrock on-demand inference is per-token and costs nothing between calls. This
project provisions no endpoint, no Provisioned Throughput, no vector store and
no SageMaker resource. Total measured cost of a full eight-model run is under
two cents, and the only thing that outlives the run is a CloudWatch log group,
which `TEARDOWN.md` removes.

Provisioned Throughput was never considered. It is the only way to serve a
fine-tuned model on Bedrock and it bills by the hour whether or not anything
calls it, which puts it in the hundreds of dollars a month. That is also why
fine-tuning is not built anywhere in this repository.
