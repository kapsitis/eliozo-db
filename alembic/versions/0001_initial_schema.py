"""initial schema: pgvector extension, problems, solution_chunks

Revision ID: 0001
Revises:
Create Date: 2026-10-11

Schema notes
------------
* Embeddings are ``vector(1536)`` — the default width of OpenAI
  ``text-embedding-3-small``. This width is fixed across both tables; changing
  it later means dropping and recreating the column *and* its HNSW index, so it
  is pinned here as a module constant.
* HNSW gives fast approximate-nearest-neighbour search at query time. The
  ``vector_cosine_ops`` opclass matches cosine-distance queries (``<=>``).
* All DDL is raw SQL via ``op.execute`` so the migration runs byte-for-byte
  identically on the macOS workstation (colima) and on the Ubuntu server.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536  # OpenAI text-embedding-3-small


def upgrade() -> None:
    # pgvector extension (idempotent; the image ships it pre-built).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.execute(
        f"""
        CREATE TABLE problems (
            id          SERIAL PRIMARY KEY,
            problem_iri TEXT NOT NULL UNIQUE,   -- e.g. LV.SOL.2020.5.1
            content     TEXT NOT NULL,          -- Markdown, may contain LaTeX
            has_image   BOOLEAN DEFAULT false,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now(),
            embedding   vector({EMBEDDING_DIM})
        );
        """
    )

    op.execute(
        f"""
        CREATE TABLE solution_chunks (
            id          SERIAL PRIMARY KEY,
            problem_id  INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
            chunk_id    INTEGER NOT NULL,       -- 0-based order within the problem
            content     TEXT NOT NULL,
            embedding   vector({EMBEDDING_DIM}),
            UNIQUE (problem_id, chunk_id)
        );
        """
    )

    # HNSW indexes: fast approximate nearest-neighbour at query time.
    op.execute(
        """
        CREATE INDEX problems_embedding_hnsw
            ON problems USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """
    )
    op.execute(
        """
        CREATE INDEX solution_chunks_embedding_hnsw
            ON solution_chunks USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """
    )

    # Foreign-key lookup index (join solution_chunks back to their problem).
    op.execute("CREATE INDEX solution_chunks_problem_id ON solution_chunks (problem_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS solution_chunks;")
    op.execute("DROP TABLE IF EXISTS problems;")
    # Leave the `vector` extension in place: other schemas may rely on it.
