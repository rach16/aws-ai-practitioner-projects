"""Load the corpus and cut it into chunks.

The corpus is this repository's own prose: the READMEs and DECISIONS files from
P1, P4 and the root. That choice is deliberate on three counts. We wrote it, so
there is no copyright question about committing it. It contains no personal
data. And, most usefully, it is prose whose answers are known, so evaluation
questions can be written with a specific correct chunk in mind, the same
ground-truth trick that made P4 scorable.

Three chunking strategies are implemented rather than one, because chunking is
the decision that most affects retrieval quality and the usual advice ("about
500 tokens, with some overlap") is a folk remedy rather than a measurement.

    fixed       cut every N characters, ignore structure
    overlap     the same, but each chunk repeats the tail of the last
    heading     cut on Markdown headings, split further only if too long

Sizes are in **characters**, not tokens. Titan's tokeniser is not exposed
through an API, so a token-based limit would be a guess dressed as precision.
Roughly four characters to a token for English prose, which makes the 1,200
character default about 300 tokens. The embedding model's real limit is 8,192
tokens, far above anything here, so the size choice is about retrieval quality
rather than about fitting.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent

# Only prose. Code and JSON results would embed badly and are not what anyone
# would ask questions about.
SOURCES = [
    "README.md",
    "p1-model-bench/README.md",
    "p1-model-bench/DECISIONS.md",
    "p1-model-bench/TEARDOWN.md",
    "p4-document-pipeline/README.md",
    "p4-document-pipeline/DECISIONS.md",
    "p4-document-pipeline/TEARDOWN.md",
]


# Nothing shorter than this becomes a chunk of its own. Two things produce
# them: a heading with little under it, and the stub left when a section does
# not divide evenly by the chunk size. Both waste an embedding call on a
# fragment and put a junk row into every search. Short sections merge forward
# into the next one; trailing stubs merge backward into the previous one.
MIN_SECTION = 120


@dataclass
class Chunk:
    id: str
    source: str
    heading: str
    text: str
    start: int
    n_chars: int


def load() -> dict[str, str]:
    out = {}
    for relative in SOURCES:
        path = REPO / relative
        if path.exists():
            out[relative] = path.read_text()
    return out


def _heading_at(text: str, position: int) -> str:
    """The heading a chunk belongs under, for the citation.

    If the chunk *starts* with a heading, that heading is the answer. Only when
    it starts mid-section do we search backwards for the one above it.

    The first version always searched backwards from `position + 1`, which
    lands inside the "#" of the chunk's own heading and therefore finds the
    previous section's. Every heading-aligned chunk was cited one section too
    early. Citations are what this project is for, and a citation that points
    at the wrong section is worse than none, because it looks checkable.
    """
    own = re.match(r"\s*#{1,6}\s+(.+)$", text[position:position + 200], re.M)
    if own:
        return own.group(1).strip()
    found = re.findall(r"^#{1,6}\s+(.+)$", text[:position], re.M)
    return found[-1].strip() if found else "(top)"


def chunk_fixed(source: str, text: str, size: int, overlap: int = 0) -> list[Chunk]:
    """Cut every `size` characters, stepping back `overlap` each time.

    Structure-blind on purpose: this is the baseline the other strategies have
    to beat. It will happily cut a sentence, a table or a code fence in half,
    and the question is how much that actually costs at retrieval time.
    """
    chunks, start, index = [], 0, 0
    step = max(1, size - overlap)
    while start < len(text):
        body = text[start:start + size].strip()
        if body:
            # A run that does not divide evenly leaves a stub at the end: a
            # 1,201-character input at size 1,200 produced a one-character
            # chunk. Glue a trailing stub onto the chunk before it rather than
            # embedding it. It is still a real cut, just not its own row.
            if chunks and len(body) < MIN_SECTION:
                previous = chunks[-1]
                previous.text = f"{previous.text}\n{body}"
                previous.n_chars = len(previous.text)
            else:
                chunks.append(Chunk(
                    id=f"{source}#{index}", source=source,
                    heading=_heading_at(text, start), text=body,
                    start=start, n_chars=len(body),
                ))
                index += 1
        start += step
    return chunks


def chunk_by_heading(source: str, text: str, max_size: int) -> list[Chunk]:
    """Split on Markdown headings, then split any oversized section further.

    The idea being tested: a section under one heading is a unit of meaning, so
    cutting there should keep related sentences together and give retrieval a
    cleaner target. The cost is wildly uneven chunk sizes, since a section can
    be two lines or two pages.
    """
    positions = [m.start() for m in re.finditer(r"^#{1,6}\s+.+$", text, re.M)]
    if not positions:
        return chunk_fixed(source, text, max_size)
    if positions[0] != 0:
        positions.insert(0, 0)
    positions.append(len(text))

    # Merge runs of short sections forward before cutting anything.
    merged: list[tuple[int, int]] = []
    pending_start = None
    for start, end in zip(positions, positions[1:]):
        if pending_start is None:
            pending_start = start
        if len(text[pending_start:end].strip()) < MIN_SECTION:
            continue
        merged.append((pending_start, end))
        pending_start = None
    if pending_start is not None and text[pending_start:].strip():
        merged.append((pending_start, len(text)))

    chunks, index = [], 0
    for start, end in merged:
        section = text[start:end].strip()
        if not section:
            continue
        if len(section) <= max_size:
            chunks.append(Chunk(
                id=f"{source}#{index}", source=source,
                heading=_heading_at(text, start), text=section,
                start=start, n_chars=len(section),
            ))
            index += 1
            continue
        # Oversized section: fall back to fixed cuts within it, keeping the heading.
        for piece in chunk_fixed(source, section, max_size):
            chunks.append(Chunk(
                id=f"{source}#{index}", source=source,
                heading=_heading_at(text, start), text=piece.text,
                start=start + piece.start, n_chars=piece.n_chars,
            ))
            index += 1
    return chunks


STRATEGIES = {
    "fixed-600": lambda s, t: chunk_fixed(s, t, 600),
    "fixed-1200": lambda s, t: chunk_fixed(s, t, 1200),
    "fixed-2400": lambda s, t: chunk_fixed(s, t, 2400),
    "overlap-1200-200": lambda s, t: chunk_fixed(s, t, 1200, overlap=200),
    "heading-1200": lambda s, t: chunk_by_heading(s, t, 1200),
    "heading-2400": lambda s, t: chunk_by_heading(s, t, 2400),
}


def build(strategy: str) -> list[Chunk]:
    cut = STRATEGIES[strategy]
    chunks = []
    for source, text in load().items():
        chunks.extend(cut(source, text))
    return chunks


def main() -> None:
    documents = load()
    total = sum(len(t) for t in documents.values())
    print(f"{len(documents)} documents, {total:,} characters\n")
    for relative, text in documents.items():
        print(f"  {relative:42} {len(text):>7,} chars")

    print(f"\n  {'strategy':20} {'chunks':>7} {'mean':>7} {'min':>6} {'max':>7}")
    print(f"  {'-' * 20} {'-' * 7} {'-' * 7} {'-' * 6} {'-' * 7}")
    summary = {}
    for name in STRATEGIES:
        chunks = build(name)
        sizes = [c.n_chars for c in chunks]
        summary[name] = {
            "chunks": len(chunks),
            "mean_chars": round(sum(sizes) / len(sizes)),
            "min_chars": min(sizes), "max_chars": max(sizes),
        }
        print(f"  {name:20} {len(chunks):>7} {summary[name]['mean_chars']:>7} "
              f"{min(sizes):>6} {max(sizes):>7}")

    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "chunking.json").write_text(json.dumps({
        "documents": {k: len(v) for k, v in documents.items()},
        "total_chars": total,
        "strategies": summary,
    }, indent=2) + "\n")
    print("\nwritten to results/chunking.json")


if __name__ == "__main__":
    main()
