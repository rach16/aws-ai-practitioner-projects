# Document pipeline results

3 synthetic documents, 22 fields with known correct answers, us-east-1. Prices fetched 2026-10-16T19:21:55+00:00.


## Accuracy and cost

| Approach | Correct | Wrong | Missing | Extract /1k | + Comprehend | Total /1k |
|---|---:|---:|---:|---:|---:|---:|
| Textract QUERIES, then Comprehend | 18 | 1 | 3 | $15.00 | $2.27 | **$17.27** |
| Textract FORMS+TABLES+QUERIES (what was actually run) | 18 | 1 | 3 | $70.00 | $2.27 | **$72.27** |
| Textract OCR only, then nova-lite | 22 | 0 | 0 | $1.55 | $2.27 | **$3.82** |
| Textract OCR only, then claude-haiku-4.5 | 22 | 0 | 0 | $2.49 | $2.27 | **$4.76** |

`Comprehend` is the same in every row: PII detection and redaction are needed whoever does the extraction, and it is the only one of the three that returns character offsets to redact by.


## Where they disagree

4 of 22 fields. On the other 18 every approach agreed.

| Field | Textract | nova-lite | claude-haiku-4.5 | Why |
|---|---|---|---|---|
| `invoice.tax_usd` | wrong | correct | correct | Label reads `Tax (9%)`. Textract returned `(9%)` at 79% confidence. |
| `invoice.contact_phone` | missing | correct | correct | Bare number on a letterhead line, no label to attach it to. |
| `paystub.employer_name` | missing | correct | correct | It is the letterhead. No field labels it as the employer. |
| `letter.appointment_date` | missing | correct | correct | Buried in prose: *see you again on 9 February 2026 at 10:30*. |

Every disagreement is a field with **no label on the page**. That is the dividing line: Textract Queries needs something to anchor to, and a language model does not.


## What the models were not asked to do

Both models returned a value for all 22 fields and used `null` zero times, though the instruction offered it and said not to guess. Here every one of those values was correct, so the difference between confident knowledge and confident invention never showed up.

That is the risk the accuracy column cannot measure. Textract's three `missing` answers are a worse score and a better failure: a missing field routes itself to a human, and a wrong field does not announce anything. Add a confidence score to that and Textract can route only the uncertain ones, which is the behaviour you want in production and the thing the model does not offer.


## Cost notes

**The feature combination is the cost decision, not the call count.** Textract prices feature combinations rather than adding features up:

| Call | Per page |
|---|---:|
| DetectDocumentText: raw text, no structure | $0.0015 |
| AnalyzeDocument with QUERIES alone | $0.0150 |
| QUERIES + TABLES | $0.0200 |
| FORMS alone | $0.0500 |
| FORMS + TABLES + QUERIES | $0.0700 |
| Same, via S3 | $0.0700 |

The first version of `extract.py` asked for FORMS, TABLES and QUERIES in one call, reasoning that one call beats three. One call does beat three calls for the same features. It does not beat asking only for what you use, and here FORMS and TABLES were never read: **$0.07 a page instead of $0.015, for identical answers.**

Comprehend's rate is hand-entered. The AWS Pricing API returns no records for AmazonComprehend in us-east-1, so $0.0001 per 100-character unit comes from https://aws.amazon.com/comprehend/pricing/ (first 10M units tier), checked 2026-10-16. Its 300-character minimum per request means four calls against a short document cost more than one call against a document four times longer.

