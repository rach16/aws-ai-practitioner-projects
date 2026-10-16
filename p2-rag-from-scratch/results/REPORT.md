# RAG from scratch: results

Generated 2026-10-16 21:35 UTC. Corpus: 7 Markdown files from this repository, 45,614 characters. 15 questions with known answers.


## Does chunking strategy matter?

Yes, and the size of the effect depends which comparison you make.

| Strategy | Chunks | recall@3 (mean of 3 dimensionalities) |
|---|---:|---:|
| `heading-1200` | 66 | 98% |
| `overlap-1200-200` | 47 | 91% |
| `fixed-1200` | 40 | 89% |
| `heading-2400` | 58 | 87% |
| `fixed-600` | 78 | 82% |
| `fixed-2400` | 22 | 67% |

**Large chunks are clearly worse.** `fixed-2400` loses a third of the answers: a 2,400-character block spans several topics, so its vector is an average of all of them and close to none. **Very small chunks are worse too**, for the opposite reason: at 600 characters an answer straddles a boundary and neither half matches.

**Structure-aware beats structure-blind at the same size**, `heading-1200` over `fixed-1200`. That gap is about one question, so it is suggestive rather than established. With 15 questions, one question is 6.7 points.


## Does embedding dimensionality matter?

| Dimensions | recall@3 | Bytes per vector |
|---:|---:|---:|
| 256 | 84% | 1,024 |
| 512 | 84% | 2,048 |
| 1024 | 88% | 4,096 |

**No, not measurably.** The spread is under one question. Titan charges per input token regardless of how many numbers it returns, so 256 dimensions costs the same to create, takes a quarter of the storage and searches roughly four times faster. On a corpus this size the larger vectors buy nothing.


## How many chunks should be retrieved?

| k | recall on `heading-1200@512` |
|---:|---:|
| 1 | 40% |
| 3 | 100% |
| 5 | 100% |

**Retrieve at least 3.** The top result is right less than half the time on every index built here, and the right chunk is in the top three almost always. Taking only the best match throws away most of the retriever's accuracy.


## What do the sources actually buy?

Three arms, same 15 questions, temperature 0. Retrieval from `heading-1200@512`, top 3.

| Model | Arm | Correct | Refused | Invented | Output tokens |
|---|---|---:|---:|---:|---:|
| `nova-lite` | RAG: sources, may refuse | **15/15** | 1 | 0 | 738 |
| `nova-lite` | No sources, may refuse | **1/15** | 14 | 0 | 122 |
| `nova-lite` | No sources, no permission to refuse | **5/15** | 1 | 10 | 5,776 |
| `claude-haiku-4.5` | RAG: sources, may refuse | **15/15** | 0 | 0 | 2,051 |
| `claude-haiku-4.5` | No sources, may refuse | **2/15** | 11 | 3 | 1,622 |
| `claude-haiku-4.5` | No sources, no permission to refuse | **2/15** | 11 | 3 | 2,944 |

`Refused` and `Correct` are counted independently: an answer can hedge and still be right, so the three columns do not sum to the total.


### The finding is model-dependent

**For `nova-lite`, the permission to refuse does all the work.** Remove that one sentence and invention goes from 0 to 10 out of 15. Put it back and the model declines 14 times instead of guessing.

**For `claude-haiku-4.5` the same sentence changes nothing**: 11 refusals with it and 11 without. It declines on its own.

So a prompt-level safety instruction verified on one model says nothing about another. The first version of this experiment had only two arms, concluded that retrieval prevents hallucination, and was measuring the refusal instruction instead.


### Being wrong is expensive

`nova-lite` spent 5,776 output tokens inventing answers and 738 citing real ones, about 8x as many. A made-up answer needs paragraphs of scaffolding; a cited one is a sentence. Grounding is cheaper and more accurate at the same time.


## Citations

- `nova-lite`: cited a source in **15/15** answers, of which **1** pointed at a source that does not contain the answer.
- `claude-haiku-4.5`: cited a source in **15/15** answers, of which **1** pointed at a source that does not contain the answer.

The wrong-citation case is the one worth watching. The answer is right and the attribution is not, which is harder to catch than a wrong answer because it looks checkable. It is also why citation coverage alone is a weak metric: every answer here carried a citation, including the ones pointing at the wrong place.


## Cost

Building all 18 indexes cost about **$0.0042** in embedding tokens. Chunking the same corpus differently embeds the same text, so token counts barely move between strategies; the exception is the overlapping strategy, which re-embeds repeated tails and costs about 18% more.

Nothing in this project bills while idle. The vector store is a SQLite file on disk: no OpenSearch collection, no provisioned capacity, nothing to tear down.

