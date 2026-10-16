# Decisions

## Synthetic documents, drawn in code

`pipeline/make_docs.py` renders every document from facts written down first.
Nothing is scanned or downloaded.

Two reasons, and the second is the one that shaped the project. The repository
is public, and a real invoice or payslip carries someone's name, address and
national identifier; anything committed stays public after deletion. Drawing
the documents means there is no real personal data to leak rather than a
redaction step that has to be perfect every time.

The useful reason: because the facts exist before the image does, every
extraction can be **scored**. `docs/ground_truth.json` is the answer key, so
Textract and two foundation models can be marked against the same 22 fields.
Most document-AI demos show a JSON blob and leave you to eyeball it.

The cost is that the documents are clean. Crisp text on white, no skew, no
coffee stain. That makes OCR easy, so anything that fails is failing at
understanding rather than at reading, which is the comparison worth making.
Real scans would be more realistic and would confound it.

## Three documents chosen to be different in kind

The invoice is a form with a table, Textract's home ground. The paystub is a
form with a social security number on it, which makes the redaction step real.
The letter is free prose with no form structure at all: Textract's FORMS
feature returns 2 pairs and 0 tables against the invoice's 10 and 2.

That third document is why the project needs both services rather than
asserting it. A pipeline tested only on invoices concludes Textract is
sufficient.

## The answer key was wrong, so the document changed

The first run marked `recipient_name` wrong: the key said "Marcus Bell" and
Textract returned "Mr Bell". The full name appeared nowhere on the page, because
the letter only said "Dear Mr Bell". The model was being marked down for
reading the document correctly.

Fixed by adding a recipient address block to the letter, which real letters
have, rather than by editing the key to match the output. Changing the key to
whatever the system returned would have made the test unfalsifiable.

This is the same failure as P1's contested sentiment label, with one
difference: P1's case was genuinely ambiguous and was kept and flagged, and
this one was simply my error and was fixed.

## Comprehend missed a phone number, so there is a regex backstop

Comprehend found `555-0133` in the letter and missed `555-0182` on the invoice.
Same format, same service, same call.

The difference is context. The letter says "you can reach the practice on
555-0133". The invoice has the number alone on a letterhead line next to an
email. **Comprehend's PII detection is contextual rather than pattern-based**,
which makes it better than a regex at ambiguous cases and unreliable on bare
identifiers.

So the first version of the pipeline produced output with a live phone number
in it, and every check passed, because the checks confirmed the pipeline ran
rather than that nothing survived it.

`BACKSTOP` in `enrich.py` runs regexes for identifiers with reliable formats
after Comprehend, and the union is redacted. A regex is blind to context and
perfect on format; Comprehend is the reverse. Neither alone is enough for a
step where one miss is the entire failure. False positives cost a redacted
string that did not need redacting, which is the cheap direction to be wrong in.

`pipeline/verify.py` then fails loudly if any known sensitive value survives.
That gate is only writable because the documents are synthetic and the exact
forbidden strings are known. On real documents you cannot write this test,
which is an argument for building against synthetic data first and an
uncomfortable fact about redaction generally.

## Low-confidence PII is reported, not redacted

`REDACT_THRESHOLD` is 0.80. Below it a finding is surfaced for review instead of
applied, because redaction is destructive.

It fires once here: `Dorchester` as an ADDRESS at 0.587. A bare town name
genuinely is ambiguous, and the behaviour you want is a human deciding rather
than the word disappearing.

## Foundation models were compared on the same OCR

Both models receive **exactly** what Textract Queries received: the same page,
read by the same OCR, the same fields requested in the same words. Giving the
model the original image would measure something else, and rewording the prompt
would measure my prompt engineering.

This matters for how the result is stated. It is not "a model instead of
Textract". Textract does the OCR in every row. What is compared is the
understanding layer on top of identical text.

The models are the two P1 identified: `nova-lite`, which tied for the best
score at the lowest cost, and `claude-haiku-4.5`, which took the JSON
extraction column outright.

## Wrong and missing are counted separately

A single accuracy figure would hide the difference between the two failure
modes, and the difference is the entire argument.

Textract returns nothing when it cannot find a field. A prompted model returns
something for every field, because that is what the instruction asks and
"nothing found" is a harder answer for a model to produce than a plausible one.

    correct     the right value
    wrong       a value, but the wrong one   costs you silently
    missing     no value offered             you know to go and look

Textract's three `missing` answers are a worse score and a better failure.
Both models used `null` zero times across 22 fields despite being offered it
and told not to guess. Here every value happened to be right, so confident
knowledge and confident invention were indistinguishable, which is precisely
the risk the accuracy column cannot measure.

## Scoring normalises before comparing

`2026-01-22` and `22 January 2026` are the same date; `5253.8` and `$5,253.80`
are the same amount. Marking either as a mismatch measures formatting, not
extraction. Money reduces to a number, dates to ISO, free text is lowercased
with punctuation stripped, and every approach gets identical treatment.

## The expensive mistake: asking for features that went unread

The first `extract.py` requested FORMS, TABLES and QUERIES in one call,
reasoning that one call is cheaper than three.

Textract prices **feature combinations**, not features added up:

| Call | Per page |
|---|---:|
| DetectDocumentText, raw text | $0.0015 |
| AnalyzeDocument, QUERIES only | $0.0150 |
| AnalyzeDocument, FORMS + TABLES + QUERIES | $0.0700 |

A 47× spread. One call does beat three calls for the same features; it does not
beat asking only for what you use. FORMS and TABLES were never read by the
scoring, so that reasoning cost **$0.07 a page instead of $0.015, for identical
answers**.

Both rows are kept in the report rather than quietly corrected, because the
mistake is more instructive than the fix.

## The async S3 path exists to document a difference, not because it was needed

Every document here is a single-page PNG, which the sync API handles from local
bytes with nothing left behind. `pipeline/s3_async.py` runs the same documents
through S3 and a polled job anyway, because the differences are not obvious
from the documentation:

- Multi-page PDF and TIFF need async. This is the only real reason to use it.
- S3 is mandatory, so there is now a resource to tear down.
- It returns a JobId, not an answer, which makes the caller asynchronous too.
- Results paginate by `NextToken`, and forgetting to follow them truncates
  output silently.
- **It is not cheaper.** $0.07 a page either way.
- It is much slower for single pages: 7 to 10 seconds wall clock against
  sub-second, for identical answers.

## Comprehend's price is hand-entered

The AWS Pricing API returns **zero records** for AmazonComprehend in us-east-1.
Textract's rates are fetched live; Comprehend's $0.0001 per 100-character unit
is copied from the public pricing page with the date checked, and flagged as
`manual` in the output.

Same situation and same handling as Anthropic in P1. The 300-character minimum
per request is the detail worth knowing: four API calls against one short
document cost more than one call against a document four times longer.

## Model token prices are read from P1

`pipeline/report.py` reads `p1-model-bench/config/pricing.json` rather than
re-fetching. Same account, same region, already solved. A second copy would be
a second thing to go stale.
