# Teardown

Nothing to do in AWS. This project created no resource.

## What exists

| Thing | Where | Bills while idle? |
|---|---|---|
| `results/vectors.db` | Your disk, 4.2 MB | No |
| Embedding and generation calls | Billed per token, already spent | No |

No bucket, no OpenSearch collection, no Knowledge Base, no endpoint, no IAM
role. The vector store is a SQLite file; deleting the directory is the entire
cleanup, and even that is optional since the file is committed.

## What it cost

About **4 cents**: roughly $0.004 to build all 18 indexes and the rest on the
generation comparison, which calls two models three times for each of 15
questions.

Worth checking against the bill, as with every project here:

Cost Explorer → filter Service = *Amazon Bedrock*, group by **Usage type**.
Look for the Titan embedding usage type alongside the Nova and Claude token
lines. Cost Explorer lags up to 24 hours.

## If you did create a Knowledge Base

This project does not, but the walkthrough in `DECISIONS.md` goes through the
console wizard as far as the vector store choice. If you clicked through to
"Review and create", you now have real infrastructure:

1. Bedrock → **Knowledge Bases** → select it → **Delete**.
2. Deleting the Knowledge Base **does not delete the vector store**. If you
   chose OpenSearch Serverless, go to the OpenSearch console → **Collections**
   and delete the collection. That is the part with a provisioned bill
   attached, and it survives the thing that created it.
3. If you chose S3 Vectors, the bucket and index are also separate and also
   remain.

That asymmetry is worth knowing generally: a managed service that provisions
infrastructure on your behalf usually will not deprovision it on your behalf.

## Not torn down

**Model invocation logging** from P1 stays on until P6 needs the audit trail.
Every Bedrock call in this project is in that log group.

**The results.** The JSON files and `REPORT.md` in `results/` are committed, so
every number can be checked without an AWS account.

`vectors.db` is **not** committed. An earlier draft of this file said it was, so
that searches could be re-run offline, which was wrong: a search has to embed
the query, and that needs Bedrock. The database only allows inspecting chunks
offline, and every rebuild rewrites all 933 blobs, so committing it would add
5 MB to the repository history each time. Rebuild it with
`python -m rag.embed` for about $0.004.
