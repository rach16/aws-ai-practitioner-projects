# Decisions

## The corpus is this repository

The 15 questions are answered by P1's and P4's README and DECISIONS files.

Three reasons. We wrote the text, so there is no copyright question about
committing it. It contains no personal data. And the answers are known in
advance, so each question can name the paragraph that answers it and both
retrieval and generation can be **scored** rather than demonstrated.

That last point is the same trick P4 used with synthetic documents, and it is
what separates a measurement from a demo. Most RAG examples show one good
answer and leave you to assume the rest.

The cost is that the corpus is small (45,614 characters, 933 chunks across all
18 indexes) and written in one voice. Conclusions about chunk size should not
be extrapolated to a million pages of mixed PDFs.

## Gold chunks are matched by substring, not by id

Each question carries a `gold_marker`: a distinctive phrase from the paragraph
that answers it. Whichever chunk contains that phrase is the gold chunk.

This is what lets one question set score six different chunking strategies.
Pinning a chunk id would mean a separate answer key per strategy, and the
comparison would then be between six differently-graded exams.

A marker can land in more than one chunk, and that is accepted rather than
forced to be unique: with overlapping chunks it is unavoidable, and a retriever
that finds any chunk containing the answer has done its job.

## Six chunking strategies, because the usual advice is folklore

"About 500 tokens with some overlap" is repeated everywhere and justified
nowhere. Three shapes are implemented and measured:

    fixed       cut every N characters, ignoring structure
    overlap     the same, but each chunk repeats the tail of the last
    heading     cut on Markdown headings, split further only if too long

The result: large chunks are clearly bad (`fixed-2400` at 67% recall@3 against
98%), small chunks are mildly bad, and structure-aware beats structure-blind at
the same size by about one question. The first of those is a real effect; the
last is one question out of fifteen and is reported as suggestive.

Sizes are in **characters, not tokens**, because Titan's tokeniser is not
exposed through an API and a token limit would be a guess dressed as precision.
Roughly four characters to a token, so 1,200 characters is about 300 tokens.

## Nothing shorter than 120 characters becomes a chunk

Two things produced tiny chunks in the first version: a heading with little
under it, and the stub left when a section does not divide evenly by the chunk
size. A 1,201-character section at size 1,200 produced a **one-character
chunk**.

Each one wastes an embedding call on a fragment and puts a junk row into every
search. Short sections now merge forward into the next; trailing stubs merge
backward into the previous.

## The citation bug, which mattered more than the chunking

`_heading_at` found the nearest Markdown heading above a chunk's start, to
label the citation. A chunk that *begins* with its own heading landed inside the
`#` and matched the **previous** section instead. Every heading-aligned chunk
was cited one section too early.

In a project whose entire output is cited answers, this is the worst available
bug: the answer is right, the attribution is wrong, and it looks checkable. It
was found by reading one search result rather than by any test, which is an
argument for reading output you think you already understand.

The fix: if a chunk starts with a heading, that heading is the citation. Only
search backwards when it starts mid-section.

## Vectors are float32 blobs in SQLite, not JSON

A 1,024-dimension vector is 4 KB as float32 and about 20 KB as a JSON array of
decimal strings, and the JSON has to be parsed back into floats on every query.

The search is an exact cosine over every row. That is the right answer at 933
vectors and the wrong one at 93 million. What a real vector database adds is an
approximate-nearest-neighbour index, HNSW or IVF, which trades exactness for
sublinear search. Knowing where that line sits is more useful than knowing
which product to buy, and it is further out than people assume: 100,000 vectors
at 1,024 dimensions is a 400 MB matrix and a dot product over it takes tens of
milliseconds.

Both sides are re-normalised before the dot product even though Titan returns
normalised vectors. It costs one pass and it keeps the function correct if the
embedding model is swapped for one that does not normalise, which is the kind
of assumption that breaks silently and looks like a quality problem.

## The query must be embedded at the corpus's dimensionality

A question embedded at 1,024 dimensions cannot be compared to chunks stored at
256. The dimensionality is therefore read back from the stored run rather than
passed in by the caller, because that mistake is a shape error if you are lucky
and silent nonsense if something reshapes.

Titan makes no distinction between embedding a query and embedding a document.
Some models do: Cohere's API takes an `input_type` of `search_query` or
`search_document` and returns different vectors for the same text. Getting that
wrong costs retrieval quality quietly, with no error.

## Retrieval and generation are scored separately

They fail for different reasons and a combined number cannot be acted on.
`evaluate.py` answers "did the right paragraph reach the model", `answer.py`
answers "given that it did, was the reply right and attributed".

Retrieval is scored by **rank**, not by similarity threshold. A cosine of 0.7
means nothing in the abstract: it depends on the model, the dimensionality and
how the corpus happens to be distributed. In this corpus a chunk that literally
contains the answer scores around 0.40, so "above 0.7 is relevant" would reject
every correct result.

## Three arms, after two gave the wrong answer

The first comparison was RAG against "no sources, but you may say you do not
know". RAG won overwhelmingly, and the conclusion written down was that
retrieval prevents hallucination.

That was wrong. Both models mostly **refused** in the control arm rather than
inventing, so the comparison was measuring the refusal instruction, not the
sources. The third arm, no sources and no permission to refuse, separates them:

| Model | May refuse | No permission |
|---|---:|---:|
| `nova-lite` | 0 invented | **10 invented** |
| `claude-haiku-4.5` | 3 invented | 3 invented |

**The sentence is a `nova-lite` fix and a `claude-haiku-4.5` no-op.** A
prompt-level safety instruction verified on one model says nothing about
another. Permission to refuse stops the invention; the sources supply the
answer. They are different fixes and conflating them credits retrieval with
something a sentence of prompt did.

## The grader was biased toward verbosity, again

*"The measurement did not account for credential resolution and the TLS
handshake on a cold client"* was marked **wrong** for not containing the
literal number `231`.

Three correct answers were scored as failures, all of them from the more
concise model, which made the wordier model look more accurate. The rules now
accept the wordings a correct answer actually produces.

This is the third time across P1, P4 and P2 that the grader has penalised
brevity. It is worth naming as a pattern rather than fixing quietly: a scorer
built by pattern-matching against a source rewards copying the source.

## Hallucinations were counted as a negative number

`invented = n − correct − refused` assumes those are exclusive. An answer can
hedge and still be right, and the arithmetic then reported **−1** hallucinations
for `nova-lite`. Counted per row now.

## Why not Bedrock Knowledge Bases

Not cost, despite what the repository README said until this project was built.
The vector store list now offers **Amazon S3 Vectors** at $0.06 per GB-month
with no minimum and no provisioned capacity: a fraction of a cent a month for
this corpus. The $350/month figure applied to the OpenSearch Serverless option
rather than to the service, and had never been verified against the Pricing
API, which publishes no `AmazonOpenSearchServerless` records at all.

The reason that survives is the one that was always stronger: **writing the
chunking and the cosine search yourself is what makes retrieval explainable.**
Four of the five findings in this project are invisible from a console. The
managed service picks a chunk size and a dimensionality for you, and both
turned out to matter — one a great deal, the other not at all, and there is no
way to tell which from the outside.
