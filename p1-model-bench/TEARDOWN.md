# Teardown

Run this when you are finished with the project. Nothing here bills while idle,
so leaving it is cheap rather than dangerous, but the point of the habit is that
the later projects in this repository are not so forgiving.

## What this project created

| Thing | Where | Bills while idle? |
|---|---|---|
| Model invocation log group | CloudWatch Logs, `/aws/bedrock/modelinvocations` | Storage only, pennies |
| Invocation logging config | Bedrock → Settings | No |
| Model invocation entitlements | Automatic on first invoke, no page to visit | No |
| IAM service role for logging | Created by the console when logging was enabled | No |

No endpoints, no Provisioned Throughput, no SageMaker domain, no vector store,
no S3 buckets. Inference is billed per token and stops when the calls stop.

## Steps

**1. Turn off model invocation logging.**
Bedrock console → **Settings** (bottom of the left sidebar) → *Model invocation
logging* → toggle off → Save.

**2. Delete the log group.**
CloudWatch console → **Log groups** → select `/aws/bedrock/modelinvocations` →
Actions → **Delete log group(s)**.

Do this second. Deleting the log group while logging is still on just means
Bedrock recreates it on the next call.

**3. There is no model access to revoke.**
The Bedrock Model access page has been retired. Serverless foundation models are
enabled automatically the first time an account invokes them, so there is no
grant to undo and nothing accrues from having invoked one. Access is controlled
through IAM policies and SCPs instead, which is where to look if you want to
restrict it.

**4. Confirm the spend.**
Billing and Cost Management → **Cost Explorer** → filter Service = *Amazon
Bedrock*, group by **Usage type**. Granularity daily.

Expect a figure in the low cents. The grouping is the interesting part: it
splits input tokens from output tokens per model, which is the same breakdown
`results/REPORT.md` projects from. Comparing the two is the honest check on
whether the report's cost model is right.

Cost Explorer lags by up to 24 hours, so same-day numbers will look low.

## What is deliberately not torn down

**The results.** `results/raw.jsonl`, `results/results.csv` and
`results/REPORT.md` are committed. The whole point is that the numbers can be
read without an AWS account and without spending anything.

**The budget alert.** The account-level AWS Budgets alert is not part of this
project and stays.
