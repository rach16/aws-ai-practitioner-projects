# AWS AI Practitioner Projects

Six small, self-contained projects built on AWS Bedrock and the managed AI services, covering every domain of the AWS Certified AI Practitioner (AIF-C01) exam.

I passed AIF-C01 in September 2026. A certification shows familiarity; these show what I can actually build with it. Each project is deliberately small enough to finish, and each one ends with a `DECISIONS.md` explaining why I chose that approach over the alternatives.

## Domain coverage

| Exam domain | Weight | Projects |
|---|---|---|
| 1 · Fundamentals of AI and ML | 20% | P4, P5 |
| 2 · Fundamentals of Generative AI | 24% | P1, P2 |
| 3 · Applications of Foundation Models | 28% | P1, P2 |
| 4 · Guidelines for Responsible AI | 14% | P3, P5 |
| 5 · Security, Compliance and Governance | 14% | P6 |

## The projects

| | Project | What it demonstrates | Status |
|---|---|---|---|
| **P1** | [Model Bench](./p1-model-bench) | Model selection by measured cost, latency and quality. Inference parameter sweeps. | **Done** |
| **P2** | [RAG from scratch](./p2-rag-from-scratch) | Chunking, embeddings, vector search and citation-backed generation, all written by hand and measured against a no-retrieval control. | **Done** |
| **P3** | [Guardrails](./p3-guardrails) | Denied topics, PII redaction and content filtering, with a model card for the RAG system. | Planned |
| **P4** | [Document pipeline](./p4-document-pipeline) | Textract and Comprehend on unstructured documents, measured against a foundation model doing the same job. | **Done** |
| **P5** | [Churn classifier](./p5-churn-classifier) | The full ML lifecycle with a real confusion matrix, precision, recall and F1. | Planned |
| **P6** | [Secure Bedrock](./p6-secure-bedrock) | Least-privilege IAM, KMS encryption and CloudTrail audit queries. | Planned |

## Cost discipline

Model inference is billed per token, so the cost of running these projects scales with use and stops when they stop. The architectural choice worth noting is what they avoid: **services that bill while idle**.

- **Bedrock Knowledge Bases** can provision OpenSearch Serverless behind it, which
bills on provisioned capacity whether queried or not. It is no longer the only
choice: the vector store list now includes **Amazon S3 Vectors**, which the AWS
Pricing API puts at **$0.06 per GB-month with no minimum and no provisioned
capacity**. For a corpus of a few hundred chunks that is a fraction of a cent a
month. P2 still builds retrieval by hand, but for the reason below rather than
for the cost.
- **SageMaker endpoints and Studio domains** bill continuously until explicitly
deleted, not when the browser tab closes. P5 runs locally.
- **Kendra** starts around $810/month. Not used, and that figure is from the
public pricing page rather than the Pricing API, which publishes no Kendra rates.

An earlier version of this README said Knowledge Bases cost roughly $350/month at
minimum. That was true of the OpenSearch Serverless option and is not true of the
service, and the figure itself came from memory: the Pricing API returns no
records for `AmazonOpenSearchServerless`, so it was never verified here. It is
left in this paragraph as a correction rather than deleted, because a cost claim
that is confidently wrong is exactly the kind of thing these projects are
supposed to catch.

**P2 builds retrieval by hand for the learning, not to save money.** Writing the
chunking, the embedding calls and the cosine search yourself is what makes
retrieval explainable in an interview, instead of describing a console button.
That reason does not depend on a price, which is just as well, because the price
changed.

An AWS Budgets alert guards the account, and each project's `DECISIONS.md` records what it actually cost to run.

## What is not built here

**Fine-tuning.** Serving a fine-tuned model on Bedrock requires Provisioned Throughput, which costs hundreds of dollars a month. Rather than skip the topic, P2's `DECISIONS.md` works through the fine-tuning versus RAG choice with real cost figures and explains why RAG wins for that workload. The reasoning is the transferable part; the invoice is not.

## Shared code

`shared/bedrock.py` is the one place in this repository that calls Bedrock. It
wraps the Converse API with retries for the errors worth retrying, a fallback
for models that reject a separate system prompt, and both latency measurements:
what the service reports it spent, and what the caller actually waited for.

It was extracted from P1 once it was clear P2 and P3 would otherwise each
inherit a slightly different copy.

## Repository conventions

Each project directory contains:

- `README.md` — what it does, how to run it, and the results
- `DECISIONS.md` — the choices made and the alternatives rejected, with reasoning
- Committed results, so the numbers can be read without running anything

Credentials come from the AWS CLI profile and are never committed.
