# P4 · Document Pipeline

Scanned page in, structured and redacted data out. Textract reads the pixels,
Comprehend finds the personal data and removes it, and a foundation model is
asked to do the same job so the choice between them can be measured instead of
assumed.

**[Full results →](results/REPORT.md)** · **[Why it was built this way →](DECISIONS.md)**
· **[Cleanup →](TEARDOWN.md)**

## The result

Three synthetic documents, 22 fields with known correct answers.

| Approach | Correct | Wrong | Missing | Cost per 1,000 docs |
|---|---:|---:|---:|---:|
| Textract OCR → `nova-lite` | **22** | 0 | 0 | **$3.82** |
| Textract OCR → `claude-haiku-4.5` | **22** | 0 | 0 | $4.76 |
| Textract `QUERIES` | 18 | 1 | 3 | $17.27 |
| Textract `FORMS+TABLES+QUERIES` *(what I ran first)* | 18 | 1 | 3 | **$72.27** |

**The cheap route is 4.5× cheaper and more accurate**, and my first
implementation cost 19× the best option for identical answers.

This is not "a model instead of Textract". Textract does the OCR in every row.
What differs is the understanding layer on top of the same extracted text.

### Where they disagree

4 of 22 fields. All four have **no label on the page**:

| Field | Textract | Models | Why |
|---|---|---|---|
| `tax_usd` | wrong | correct | Label reads `Tax (9%)`; Textract returned `(9%)` at 79% confidence |
| `contact_phone` | missing | correct | Bare number on a letterhead line |
| `employer_name` | missing | correct | It *is* the letterhead |
| `appointment_date` | missing | correct | In prose: *"see you again on 9 February 2026 at 10:30"* |

That is the dividing line. Textract Queries needs something to anchor to; a
language model does not.

### The result the accuracy column cannot show

Both models answered all 22 fields and used `null` **zero times**, though the
prompt offered it and said not to guess. Every value happened to be right, so
confident knowledge and confident invention were indistinguishable.

Textract's three `missing` answers are a worse score and a better failure. A
missing field routes itself to a human; a wrong field announces nothing. Pair
that with Textract's per-field confidence and only the uncertain cases need
review, which is the behaviour you want in production and the thing the model
does not offer.

So the honest recommendation is not "use the model". It is: **use OCR plus a
model when a wrong answer is recoverable, and Textract Queries when a silent
wrong answer is not.**

## Two bugs worth more than the results

**Comprehend missed a phone number, and my first explanation was wrong.** The
pipeline redacted the letter's phone and left the invoice's in place. I wrote
that up as "PII detection is contextual, and the invoice line was too bare".
Pasting that bare line into the Comprehend console disproved it in ten seconds:
alone, the number is found at 0.978.

[`pii_context_test.py`](pipeline/pii_context_test.py) adds the invoice back a
section at a time:

| Separator | 98 chars | 204 chars | 343 chars | full doc |
|---|---:|---:|---:|---:|
| `·` as drawn | **0.978** | 0.573 | MISSED | MISSED |
| `-` as OCR'd | **0.538** | MISSED | MISSED | MISSED |

Two variables, **neither of which is the phone number** — it is byte-for-byte
identical in every row. Unrelated text suppresses the detection as it
accumulates, and one punctuation character, a middle dot that Textract OCRs as
a hyphen, costs 0.44 on its own. At 0.538 the real pipeline was already below
its 0.80 threshold before any of the invoice was added.

**A redaction step validated on a snippet is not validated.** Detection is a
property of the whole input, not of the identifier. So the pipeline carries a
regex backstop for reliably-formatted identifiers, and
[`verify.py`](pipeline/verify.py) exits non-zero if any known sensitive value
reaches the output — checking the result rather than trusting the detector,
which is the only check that would have caught this.

**Asking for features I never read cost 4.7×.** Textract prices feature
*combinations*, not features added together: $0.0015 a page for raw OCR,
$0.015 for QUERIES, $0.07 for FORMS + TABLES + QUERIES. I requested all three
on the reasoning that one call beats three. One call does beat three calls for
the same features. It does not beat asking only for what you use, and FORMS and
TABLES were never read.

Both the expensive and the cheap row are kept in the report, because the
mistake is more instructive than the fix.

## How it works

```
docs/*.png ──> Textract ──> text + key/values + tables + query answers
                  │
                  ├──> Comprehend ──> entities, PII spans, sentiment
                  │                        │
                  │                        └──> redact ──> verify (fails on leak)
                  │
                  └──> text ──> foundation model ──> the same fields as JSON
                                                            │
                   ground_truth.json ──> score ────────────┘
```

| Module | Does |
|---|---|
| [`make_docs.py`](pipeline/make_docs.py) | Draws the documents and writes the answer key |
| [`extract.py`](pipeline/extract.py) | Textract: FORMS, TABLES, QUERIES |
| [`enrich.py`](pipeline/enrich.py) | Comprehend: entities, PII, sentiment, redaction |
| [`verify.py`](pipeline/verify.py) | Fails if anything sensitive survived |
| [`llm.py`](pipeline/llm.py) | The same fields, asked of two Bedrock models |
| [`score.py`](pipeline/score.py) | Normalise, then mark all three against the key |
| [`pricing.py`](pipeline/pricing.py) | Live Textract rates from the Pricing API |
| [`s3_async.py`](pipeline/s3_async.py) | The async path, for the write-up |
| [`report.py`](pipeline/report.py) | Accuracy and cost in one table |

## The documents are synthetic, on purpose

Every name, address, email, phone number and social security number in `docs/`
is invented, and the images are drawn in code from facts written down first.

The repository is public, and anything committed stays public after deletion.
But the better reason is that writing the facts first means every extraction
can be **scored**, and it is what makes `verify.py` possible at all: the exact
strings that must not survive redaction are already known. On real documents
you cannot write that test.

## Sync vs async

`s3_async.py` runs the same documents through S3 and a polled job. Nothing here
needs it; it exists because the differences are not obvious from the docs.

- Multi-page PDF and TIFF **require** async. That is the only real reason.
- S3 is mandatory, so there is now something to tear down.
- It returns a `JobId`, not an answer.
- Results paginate by `NextToken`; miss that and output truncates silently.
- **Not cheaper.** $0.07 a page either way.
- Much slower for single pages: 7–10 s wall clock against sub-second, for
  identical answers.

## Running it

Needs an AWS profile named `personal` with Textract, Comprehend and Bedrock in
us-east-1. For the async step, copy `config/local.example.json` to
`config/local.json` and set your own bucket.

```bash
python -m venv .venv && ./.venv/bin/pip install -r p4-document-pipeline/requirements.txt
cd p4-document-pipeline

python -m pipeline.make_docs    # draw documents + ground truth
python -m pipeline.pricing      # live Textract rates
python -m pipeline.extract      # Textract
python -m pipeline.enrich       # Comprehend + redaction
python -m pipeline.verify       # leak gate, non-zero exit on failure
python -m pipeline.llm          # the model comparison
python -m pipeline.score        # mark everything
python -m pipeline.report       # -> results/REPORT.md

python -m pipeline.s3_async     # optional, needs the bucket
```

A full run is well under a cent. See [TEARDOWN.md](TEARDOWN.md) for the bucket.

## Exam domains

Domain 1 (Fundamentals of AI and ML): service selection for unstructured data,
and where a managed AI service beats a foundation model and where it does not.
Domain 4 (Responsible AI): PII detection, redaction and the confidence
threshold that decides what a human looks at.
