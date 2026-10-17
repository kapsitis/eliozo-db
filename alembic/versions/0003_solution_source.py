"""solution source: solution_chunks.solution_iri, solution_chunks.updated_at

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18

``scripts/index_problems.py`` loads problems and solutions from TTL files and
embeds them incrementally. To tell which solution a chunk came from (one
problem may have several solutions, each in several languages) it records the
solution's IRI, and like ``problems.updated_at`` each chunk records when it was
last written. Nullable / defaulted, so rows written by the Flask app's
``load_problems`` (which knows neither) still fit.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE solution_chunks ADD COLUMN solution_iri TEXT;")
    op.execute("ALTER TABLE solution_chunks ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();")


def downgrade() -> None:
    op.execute("ALTER TABLE solution_chunks DROP COLUMN updated_at;")
    op.execute("ALTER TABLE solution_chunks DROP COLUMN solution_iri;")
