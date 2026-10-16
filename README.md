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
| **P2** | [RAG from scratch](./p2-rag-from-scratch) | Chunking, embeddings, vector search and citation-backed generation, with retrieval written by hand. | Planned |
| **P3** | [Guardrails](./p3-guardrails) | Denied topics, PII redaction and content filtering, with a model card for the RAG system. | Planned |
| **P4** | [Document pipeline](./p4-document-pipeline) | Textract and Comprehend on unstructured documents, measured against a foundation model doing the same job. | **Done** |
| **P5** | [Churn classifier](./p5-churn-classifier) | The full ML lifecycle with a real confusion matrix, precision, recall and F1. | Planned |
| **P6** | [Secure Bedrock](./p6-secure-bedrock) | Least-privilege IAM, KMS encryption and CloudTrail audit queries. | Planned |

## Cost discipline

Model inference is billed per token, so the cost of running these projects scales with use and stops when they stop. The architectural choice worth noting is what they avoid: **services that bill while idle**.

- **Bedrock Knowledge Bases** provisions OpenSearch Serverless behind it, which bills roughly $350/month at minimum capacity whether queried or not. P2 builds retrieval by hand instead.
- **SageMaker endpoints and Studio domains** bill continuously until explicitly deleted, not when the browser tab closes. P5 runs locally.
- **Kendra** starts around $810/month. Not used.

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
