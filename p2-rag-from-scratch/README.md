# P2 · RAG from scratch

Chunk, embed, store, search, answer with citations. No Knowledge Base, no
managed vector store, no framework. About 900 lines, and the vector database is
a SQLite file.

The corpus is **this repository's own README and DECISIONS files**. We wrote
them, so there is no copyright question and no personal data, and more usefully
the answers are known: 15 questions each have a specific correct paragraph, so
retrieval and generation can both be scored instead of demonstrated.

**[Full results →](results/REPORT.md)** · **[Why it was built this way →](DECISIONS.md)**
· **[Cleanup →](TEARDOWN.md)**

## What was measured

Six chunking strategies × three embedding dimensionalities = **18 indexes**,
each scored on whether it puts the answer in the top k.

### Chunking matters, and the usual advice is roughly right

| Strategy | Chunks | recall@3 |
|---|---:|---:|
| `heading-1200` | 66 | **98%** |
| `overlap-1200-200` | 47 | 91% |
| `fixed-1200` | 40 | 89% |
| `heading-2400` | 58 | 87% |
| `fixed-600` | 78 | 82% |
| `fixed-2400` | 22 | **67%** |

**Big chunks are clearly bad.** A 2,400-character block covers several topics,
so its vector is the average of all of them and close to none. **Small chunks
are bad too**, for the opposite reason: at 600 characters the answer straddles
a boundary and neither half matches well.

Cutting on Markdown headings beat cutting blindly at the same size, but by
about one question, so it is suggestive rather than proven.

### Dimensionality does not matter here

| Dimensions | recall@3 | Bytes per vector |
|---:|---:|---:|
| 256 | 84% | 1,024 |
| 512 | 84% | 2,048 |
| 1024 | 88% | 4,096 |

A spread of under one question. Titan charges **per input token regardless of
how many numbers it returns**, so 256 dimensions costs the same to create,
takes a quarter of the storage and searches about four times faster. On a
corpus this size the larger vectors buy nothing.

### Retrieve at least three

The top result is correct **less than half the time** on every index built
here, and the right chunk is in the top three almost always. Taking only the
best match throws away most of the retriever's accuracy.

## What the sources actually buy

Three arms, same 15 questions, temperature 0.

| Model | Arm | Correct | Refused | Invented |
|---|---|---:|---:|---:|
| `nova-lite` | RAG: sources, may refuse | **15/15** | 1 | 0 |
| `nova-lite` | No sources, may refuse | 1/15 | 14 | 0 |
| `nova-lite` | No sources, **no permission to refuse** | 5/15 | 1 | **10** |
| `claude-haiku-4.5` | RAG: sources, may refuse | **15/15** | 0 | 0 |
| `claude-haiku-4.5` | No sources, may refuse | 2/15 | 11 | 3 |
| `claude-haiku-4.5` | No sources, no permission to refuse | 2/15 | 11 | 3 |

### The result is model-dependent, which is the point

**For `nova-lite` the permission to refuse does all the work.** One sentence —
*"if you do not know, say you do not know"* — is the difference between 10
invented answers and 0.

**For `claude-haiku-4.5` that sentence changes nothing.** Eleven refusals with
it, eleven without. It declines on its own.

So a prompt-level safety instruction verified on one model tells you nothing
about another. This only became visible because of the third arm. The first
version of the experiment had two, concluded that retrieval prevents
hallucination, and was actually measuring the refusal instruction.

### Being wrong costs 8× more

`nova-lite` spent **5,776 output tokens** inventing answers and **738** citing
real ones. A fabricated answer needs paragraphs of scaffolding; a grounded one
is a sentence. Grounding is cheaper and more accurate at the same time.

## The measurement was wrong four times

Every one of these produced a plausible table:

**The citations pointed at the wrong section.** `_heading_at` searched backwards
from a chunk's start for the nearest heading. A chunk that *begins* with its own
heading landed inside the `#` and found the previous section's. Every
heading-aligned chunk was cited one section early — in a project whose whole
output is citations.

**Chunks of one character.** A heading with nothing under it, and the stub left
when a section does not divide evenly, each became a chunk: an embedding call
spent on the word "Open" and a junk row in every search.

**The grader penalised brevity.** *"The measurement did not account for
credential resolution and the TLS handshake on a cold client"* was marked wrong
for not containing the literal number `231`. Three correct answers were scored
as failures, all from the more concise model.

**Hallucinations were counted as a negative number.** `invented = n − correct −
refused` assumes those are exclusive. An answer can hedge and still be right,
and the arithmetic then reports −1 hallucinations.

Across P1, P4 and P2 the instrument has been wrong more often than the thing
being measured, and the grader has been biased toward verbosity three separate
times.

## How it works

```
7 markdown files
      │
      ├── corpus.py    cut into chunks (6 strategies)
      ├── embed.py     Titan v2 → vectors (3 dimensionalities)
      └── store.py     SQLite: text in one table, float32 blobs in another
                              │
 question ── embed ──────────►│ cosine ── top 3 chunks
                                              │
                                              ├── evaluate.py  is the answer in the top k?
                                              └── answer.py    paste above the question,
                                                               demand a citation
```

| Module | Does |
|---|---|
| [`corpus.py`](rag/corpus.py) | Load the Markdown, three chunking strategies |
| [`store.py`](rag/store.py) | The "vector database": SQLite plus a dot product |
| [`embed.py`](rag/embed.py) | Titan Text Embeddings v2, builds all 18 indexes |
| [`search.py`](rag/search.py) | Embed the question, return the nearest chunks |
| [`evaluate.py`](rag/evaluate.py) | recall@1/3/5 for every index |
| [`answer.py`](rag/answer.py) | Generation, citations, and the three-arm comparison |
| [`report.py`](rag/report.py) | Assembles the results |

## The vector store is a SQLite file

`results/vectors.db`, about 5 MB and gitignored. Three tables: 18 index definitions, 933 chunk
rows, 933 vector blobs. A 256-dimension vector is 1,024 bytes of float32.

What a real vector database adds is an approximate-nearest-neighbour index so
search stops being linear in the number of vectors. This does an exact search
over every row, which is right at 933 and wrong at 93 million. Knowing where
that line sits is more useful than knowing which product to buy, and it is
further out than people assume: 100,000 vectors at 1,024 dimensions is a 400 MB
matrix and a dot product over it takes tens of milliseconds.

## Why not Bedrock Knowledge Bases

Not cost, despite what an earlier version of the repository README claimed. The
vector store list now includes **Amazon S3 Vectors** at $0.06 per GB-month with
no minimum and no provisioned capacity, which for this corpus is a fraction of
a cent a month. The old $350/month figure applied to the OpenSearch Serverless
option, not to the service, and was never verified.

The reason that survives: **writing the chunking and the cosine search yourself
is what makes retrieval explainable.** Four of the five findings above are
invisible from a console. The managed service would have picked a chunk size
and a dimensionality for you, and both turned out to matter — one of them a lot,
the other not at all, and you cannot tell which without measuring.

## Running it

Needs an AWS profile named `personal` with Bedrock access in us-east-1.

```bash
python -m venv .venv && ./.venv/bin/pip install -r p2-rag-from-scratch/requirements.txt
cd p2-rag-from-scratch

python -m rag.corpus       # chunking statistics
python -m rag.embed        # build all 18 indexes  (~5 min, $0.004)
python -m rag.evaluate     # recall@k for every index
python -m rag.answer       # three-arm generation comparison
python -m rag.report       # -> results/REPORT.md

python -m rag.search "why was fine-tuning not built"   # ad hoc query
```

Whole project is about 4 cents. Nothing bills while idle, nothing to tear down:
see [TEARDOWN.md](TEARDOWN.md).

## Exam domains

Domain 2 (Fundamentals of Generative AI) and Domain 3 (Applications of
Foundation Models): embeddings, vector stores, chunking, retrieval-augmented
generation, prompt engineering for grounding and refusal, and the difference
between a model that does not know and a model that will not say so.
