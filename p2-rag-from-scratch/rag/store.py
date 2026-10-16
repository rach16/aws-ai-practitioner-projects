"""The vector store: a SQLite file and a numpy dot product.

This is the part that a managed service would hide, and the reason P2 exists.
A vector store does two things: keep an array of floats next to the text it
came from, and find the nearest ones to a query vector. At this scale that is
a table and one matrix multiply.

What a real vector database adds is an approximate-nearest-neighbour index,
HNSW or IVF, which stops the search being linear in the number of vectors. We
do an exact search over every row, which is the *right* answer at 78 chunks and
the wrong one at 78 million. Knowing where that line sits is more useful than
knowing which product to buy, and the line is a lot further out than people
expect: 100,000 vectors at 1,024 dimensions is a 400 MB matrix and a dot
product takes tens of milliseconds.

Vectors are stored as raw float32 bytes rather than JSON. A 1,024-dimension
vector is 4 KB as float32 and about 20 KB as a JSON array of decimal strings,
and the JSON has to be parsed back into floats on every single query.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "results" / "vectors.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    run_id    TEXT NOT NULL,
    chunk_id  TEXT NOT NULL,
    source    TEXT NOT NULL,
    heading   TEXT NOT NULL,
    text      TEXT NOT NULL,
    n_chars   INTEGER NOT NULL,
    PRIMARY KEY (run_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS vectors (
    run_id    TEXT NOT NULL,
    chunk_id  TEXT NOT NULL,
    dims      INTEGER NOT NULL,
    vec       BLOB NOT NULL,
    PRIMARY KEY (run_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    strategy      TEXT NOT NULL,
    model_id      TEXT NOT NULL,
    dims          INTEGER NOT NULL,
    n_chunks      INTEGER NOT NULL,
    input_tokens  INTEGER NOT NULL,
    built_at      TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def run_id(strategy: str, dims: int) -> str:
    return f"{strategy}@{dims}"


def save_run(conn, rid: str, strategy: str, model_id: str, dims: int,
             chunks: list, vectors: np.ndarray, input_tokens: int, built_at: str) -> None:
    conn.execute("DELETE FROM chunks  WHERE run_id = ?", (rid,))
    conn.execute("DELETE FROM vectors WHERE run_id = ?", (rid,))

    conn.executemany(
        "INSERT INTO chunks (run_id, chunk_id, source, heading, text, n_chars) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(rid, c.id, c.source, c.heading, c.text, c.n_chars) for c in chunks],
    )
    conn.executemany(
        "INSERT INTO vectors (run_id, chunk_id, dims, vec) VALUES (?, ?, ?, ?)",
        [(rid, c.id, dims, v.astype(np.float32).tobytes())
         for c, v in zip(chunks, vectors)],
    )
    conn.execute(
        "INSERT OR REPLACE INTO runs "
        "(run_id, strategy, model_id, dims, n_chunks, input_tokens, built_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rid, strategy, model_id, dims, len(chunks), input_tokens, built_at),
    )
    conn.commit()


def load_run(conn, rid: str) -> tuple[list[dict], np.ndarray]:
    """Chunk metadata and the matrix of vectors, in the same order."""
    rows = conn.execute(
        "SELECT c.chunk_id, c.source, c.heading, c.text, v.vec, v.dims "
        "FROM chunks c JOIN vectors v "
        "  ON c.run_id = v.run_id AND c.chunk_id = v.chunk_id "
        "WHERE c.run_id = ? ORDER BY c.rowid", (rid,),
    ).fetchall()
    if not rows:
        raise KeyError(f"no run {rid!r} in {DB_PATH.name}")

    meta = [{"chunk_id": r[0], "source": r[1], "heading": r[2], "text": r[3]} for r in rows]
    matrix = np.vstack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
    return meta, matrix


def list_runs(conn) -> list[dict]:
    columns = ["run_id", "strategy", "model_id", "dims", "n_chunks", "input_tokens", "built_at"]
    return [dict(zip(columns, row)) for row in
            conn.execute(f"SELECT {', '.join(columns)} FROM runs ORDER BY run_id")]


def cosine_search(query: np.ndarray, matrix: np.ndarray, k: int) -> list[tuple[int, float]]:
    """Top-k by cosine similarity. Exact, over every row.

    Titan returns normalised vectors when asked, so a dot product is already
    the cosine. Both sides are normalised here anyway: it costs one pass and it
    means the function is still correct if the embedding model changes to one
    that does not normalise, which is the kind of assumption that breaks
    silently and looks like a quality problem.
    """
    q = query / (np.linalg.norm(query) + 1e-12)
    m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)
    scores = m @ q
    top = np.argsort(-scores)[:k]
    return [(int(i), float(scores[i])) for i in top]
