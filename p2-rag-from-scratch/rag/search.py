"""Query side: embed the question, find the nearest chunks.

One detail here is easy to get wrong and expensive to debug. The query must be
embedded by **the same model at the same dimensionality** as the corpus. A
question embedded at 1,024 dimensions cannot be compared to chunks stored at
256: the dot product is a shape error if you are lucky and silent nonsense if
the code reshapes. The dimensionality is therefore read back from the stored
run rather than passed in by the caller.

Titan makes no distinction between embedding a query and embedding a document.
Some models do: Cohere's embed API takes an `input_type` of `search_query` or
`search_document` and produces different vectors for the same text depending
which you ask for. Using the wrong one there costs retrieval quality quietly,
with no error.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import rag._path  # noqa: F401
from rag.embed import client, embed_one
from rag.store import connect, cosine_search, load_run


@dataclass
class Hit:
    rank: int
    score: float
    chunk_id: str
    source: str
    heading: str
    text: str


class Index:
    """One built index, held in memory for repeated queries."""

    def __init__(self, conn, rid: str, bedrock=None):
        self.rid = rid
        self.meta, self.matrix = load_run(conn, rid)
        self.dims = self.matrix.shape[1]
        self.bedrock = bedrock or client()

    def search(self, question: str, k: int = 5) -> list[Hit]:
        vector, _ = embed_one(self.bedrock, question, self.dims)
        return [
            Hit(rank=rank, score=score, **{
                key: self.meta[i][key] for key in ("chunk_id", "source", "heading", "text")
            })
            for rank, (i, score) in enumerate(cosine_search(vector, self.matrix, k))
        ]


def main() -> None:
    import sys
    question = " ".join(sys.argv[1:]) or "Why was fine-tuning not built?"
    conn = connect()
    index = Index(conn, "heading-1200@1024")
    print(f"{question!r}  against {index.rid}\n")
    for hit in index.search(question, k=4):
        preview = " ".join(hit.text.split())[:110]
        print(f"  {hit.score:.3f}  {hit.source} · {hit.heading}")
        print(f"         {preview}...\n")


if __name__ == "__main__":
    main()
