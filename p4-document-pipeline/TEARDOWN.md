# Teardown

Unlike P1, this project leaves something behind that costs money. Do this when
you are finished.

## What exists

| Thing | Where | Bills while idle? |
|---|---|---|
| 3 PNG objects | `s3://<your-bucket>/p4-docs/` | Yes, storage |
| The S3 bucket | S3 console | Only for what it holds |
| Textract jobs | Nothing persists, jobs expire after 7 days | No |
| Comprehend calls | Synchronous, nothing stored | No |

Three small PNGs cost a fraction of a cent a month. The habit is the point: a
bucket you forgot is how a learning account turns into a surprise.

## Steps

**1. Empty the bucket.**
S3 console → your bucket → **Empty** → type `permanently delete` → Empty.

A bucket cannot be deleted while it holds anything, and the error message when
you try does not say so clearly.

**2. Delete the bucket.**
S3 console → select the bucket → **Delete** → type the bucket name → Delete.

By CLI, if you prefer, replacing the name with your own:

```bash
aws s3 rm s3://YOUR-BUCKET --recursive --profile personal
aws s3 rb s3://YOUR-BUCKET --profile personal
```

**3. Leave `config/local.json` alone.**
It is gitignored and holds only your bucket name. Delete it if you want the
repository clean; nothing breaks either way, and `config/local.example.json`
documents the shape.

**4. Check the spend.**
Cost Explorer → filter Service = *Amazon Textract* and *Amazon Comprehend*,
group by **Usage type**.

The grouping is the useful part. Textract bills per feature combination, so you
should see `SyncFormsQueriesTablesPagesProcessed` at $0.07 a page for the first
runs and `SyncQueriesPagesProcessed` at $0.015 for later ones. That difference
is the single most expensive mistake in this project and it is visible in the
bill.

Cost Explorer lags up to 24 hours.

## Not torn down

**Model invocation logging** from P1 stays on until P6 needs the audit trail.

**The results.** `results/` is committed so the numbers can be read without an
AWS account and without spending anything.
