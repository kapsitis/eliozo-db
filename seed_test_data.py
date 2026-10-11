"""Insert a handful of test rows so the schema can be exercised.

This is throwaway sanity data: the problem/solution *text* is parsed from real
``content_lv.md`` files under ``math/problembase`` so the rows look realistic,
but the embeddings are RANDOM — they are not produced by any model and must not
be used for real similarity search.

Markdown layout (per the project convention):

    # <lo-.../> PROBLEM.IRI          <- H1 starts a problem; IRI is the last token
    ...problem statement...
    <small> ...metadata... </small>  <- end of the problem statement
    ## Atrisinājums                  <- each such section is one solution_chunk
    ...solution text...
    # <lo-.../> NEXT.PROBLEM.IRI     <- next problem

Run:  python seed_test_data.py
Idempotent: re-running upserts the same problems by problem_iri.
"""

import os
import random
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

load_dotenv(Path(__file__).resolve().parent / ".env")

EMBEDDING_DIM = 1536

# A source file that has the full structure (H1 + <small> + ## Atrisinājums +
# an image), so every column gets exercised.
SOURCE = (
    Path.home()
    / "workspace/math/problembase/LV.SOL/lv-sol-2020/content_lv.md"
)
MAX_PROBLEMS = 5  # keep the test set small


def dummy_embedding() -> list[float]:
    """A random unit-ish vector. NOT a real embedding."""
    return [random.uniform(-1.0, 1.0) for _ in range(EMBEDDING_DIM)]


def parse_problems(markdown: str):
    """Yield (problem_iri, content, has_image, [chunk_texts])."""
    # Split into blocks that each begin with an H1 line.
    blocks = re.split(r"(?m)^(?=#\s)", markdown)
    for block in blocks:
        block = block.strip()
        if not block.startswith("# "):
            continue
        lines = block.splitlines()
        h1 = lines[0]
        # IRI is the last whitespace-separated token of the H1 (drop any tag).
        iri = h1.lstrip("# ").split()[-1]

        # Problem statement: from after the H1 up to the <small> block (or, if
        # there is none, up to the first "## " heading).
        rest = "\n".join(lines[1:])
        small = re.search(r"<small>.*?</small>", rest, re.DOTALL)
        if small:
            content = rest[: small.start()].strip()
            after = rest[small.end():]
        else:
            split = re.search(r"(?m)^##\s", rest)
            content = (rest[: split.start()] if split else rest).strip()
            after = rest[split.start():] if split else ""

        # Each "## ..." section in the trailing region is one solution chunk.
        chunks = [c.strip() for c in re.split(r"(?m)^##\s+", after) if c.strip()]

        if not content:
            continue
        has_image = "![" in block
        yield iri, content, has_image, chunks


def main() -> None:
    conn_str = (
        f"host={os.environ.get('DB_HOST', 'localhost')} "
        f"port={os.environ.get('DB_PORT', '5432')} "
        f"dbname={os.environ['DB_NAME']} "
        f"user={os.environ['DB_USER']} "
        f"password={os.environ['DB_PASSWORD']}"
    )
    markdown = SOURCE.read_text(encoding="utf-8")
    problems = list(parse_problems(markdown))[:MAX_PROBLEMS]

    with psycopg.connect(conn_str) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            for iri, content, has_image, chunks in problems:
                cur.execute(
                    """
                    INSERT INTO problems (problem_iri, content, has_image, embedding)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (problem_iri) DO UPDATE
                        SET content   = EXCLUDED.content,
                            has_image = EXCLUDED.has_image,
                            embedding = EXCLUDED.embedding,
                            updated_at = now()
                    RETURNING id;
                    """,
                    (iri, content, has_image, dummy_embedding()),
                )
                problem_id = cur.fetchone()[0]

                # Replace any previous chunks for a clean re-run.
                cur.execute(
                    "DELETE FROM solution_chunks WHERE problem_id = %s;",
                    (problem_id,),
                )
                for chunk_id, chunk in enumerate(chunks):
                    cur.execute(
                        """
                        INSERT INTO solution_chunks
                            (problem_id, chunk_id, content, embedding)
                        VALUES (%s, %s, %s, %s);
                        """,
                        (problem_id, chunk_id, chunk, dummy_embedding()),
                    )
                print(f"  {iri}: has_image={has_image}, {len(chunks)} chunk(s)")
        conn.commit()

    print(f"Seeded {len(problems)} problem(s) from {SOURCE.name}.")


if __name__ == "__main__":
    main()
