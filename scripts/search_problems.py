"""Nearest problems to a query, by cosine similarity of OpenAI embeddings.

Usage:
    python search_problems.py "query text" [--limit 10] [--solutions]

Prints problem IDs ranked by similarity (1 - cosine distance; for OpenAI
embeddings of real text it lies between 0 and 1, higher is closer). With
``--solutions`` the solution chunks are searched instead of the statements.
A quick check of the index from the command line; the Flask app has its own
search (``eliozo_dao.postgres.semantic_search``).
"""

import argparse
import sys

from openai import OpenAI
from sqlalchemy import create_engine, text

import dbenv
from index_problems import embed_texts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('query')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--solutions', action='store_true', help='search solution chunks')
    args = parser.parse_args(argv)

    engine = create_engine(dbenv.sqlalchemy_url())
    vector = str(embed_texts(OpenAI(timeout=30.0), [args.query])[0])
    if args.solutions:
        sql = ('SELECT p.problem_iri, 1 - (s.embedding <=> CAST(:v AS vector)) AS similarity, s.content '
               'FROM solution_chunks s JOIN problems p ON p.id = s.problem_id '
               'WHERE s.embedding IS NOT NULL ORDER BY s.embedding <=> CAST(:v AS vector) LIMIT :n')
    else:
        sql = ('SELECT problem_iri, 1 - (embedding <=> CAST(:v AS vector)) AS similarity, content '
               'FROM problems WHERE embedding IS NOT NULL '
               'ORDER BY embedding <=> CAST(:v AS vector) LIMIT :n')
    with engine.begin() as conn:
        conn.execute(text('SET LOCAL hnsw.ef_search = %d' % max(40, args.limit)))
        rows = conn.execute(text(sql), dict(v=vector, n=args.limit)).fetchall()
    for rank, (iri, similarity, content) in enumerate(rows, 1):
        preview = ' '.join(content.split())[:70]
        print('%2d  %.4f  %-22s %s' % (rank, similarity, iri, preview))
    return 0 if rows else 1


if __name__ == '__main__':
    sys.exit(main())
