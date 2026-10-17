"""text language: problems.lang, solution_chunks.lang

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17

Problems and solutions exist in several translations (``lv``, ``en``, ``lt``
...). The Flask search results link a solution match to that solution in the
language it matched in (``/problem_solution?problemid=...&lang=lv``), so each
stored text records its language. Nullable: rows loaded before this migration
have no language and the app then lets the problem page choose one.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE problems ADD COLUMN lang TEXT;")
    op.execute("ALTER TABLE solution_chunks ADD COLUMN lang TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE solution_chunks DROP COLUMN lang;")
    op.execute("ALTER TABLE problems DROP COLUMN lang;")
