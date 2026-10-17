"""Load problems and solutions from TTL files into PostgreSQL and embed them.

Usage:
    python index_problems.py <parent-dir>              # sync, then embed
    python index_problems.py <parent-dir> --sync-only  # no OpenAI calls

<parent-dir> is searched recursively for ``*.ttl`` files, e.g. the output of
``worksheet-generation-with-llms/scripts/setup/problems_to_turtle.py``
(``.../scripts/setup/temp``). Connection and API key come from ``.env``
(see ``dbenv.py``). Safe to interrupt and re-run.

1. Sync (one transaction, no API calls). Every ``eliozo:Problem`` with a
   non-empty ``eliozo:problemText`` becomes one ``problems`` row (Latvian text
   if the problem has several languages), keyed by ``eliozo:problemID``. Every
   ``eliozo:solutionText`` of its ``eliozo:problemSolution`` solutions becomes
   one ``solution_chunks`` row (per solution and language), unless the text is
   shorter than MIN_SOLUTION_CHARS: such texts are bare answers ("For example,
   $49999$ and $50000$.") that embed to noise.
   A problem already in the table is rewritten only if one of the TTL files
   it comes from is newer than its ``updated_at``. A rewritten text whose
   content changed loses its embedding; an unchanged one keeps it.
   Problems in the database that are no longer in the TTL files are kept.
2. Embed. Rows with ``embedding IS NULL`` are embedded with OpenAI
   ``text-embedding-3-small`` in batches, each batch committed, so an
   interrupted run resumes where it stopped and never pays twice for a text.

What is embedded is the stored Markdown, lightly cleaned (``embedding_input``):
headings, images and HTML tags are dropped, LaTeX is kept as written. The
model has seen plenty of LaTeX and handles it well, while spelling formulas
out in words would need an extra LLM pass per text and would not match how
users type queries anyway.
"""

import argparse
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI
from rdflib import RDF, Graph, Namespace
from sqlalchemy import create_engine, text

import dbenv

ELIOZO = Namespace('http://www.dudajevagatve.lv/eliozo#')

# The TTL files contain literals like "None"^^xsd:integer (eliozo:problem_number);
# rdflib logs a traceback for each. They are not read here, so keep quiet.
logging.getLogger('rdflib.term').setLevel(logging.CRITICAL)

EMBEDDING_MODEL = 'text-embedding-3-small'
EMBEDDING_DIM = 1536            # vector(1536) in the Alembic migration
BATCH = 100                     # texts per OpenAI request and per commit
MAX_INPUT_CHARS = 8000          # stays below the model's 8191-token limit
MIN_SOLUTION_CHARS = 140        # shorter (cleaned) solutions are not stored
PROBLEM_LANGUAGE = 'lv'         # preferred language of the stored statement


# ── Text cleaning ─────────────────────────────────────────────────────────────

_HEADING = re.compile(r'^[ \t]*#{1,6}[ \t].*$', re.M)          # ## Atrisinājums
_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]*\)(\{[^}]*\})?')        # ![](x.png){ width=250px }
_HTML_TAG = re.compile(r'</?[a-zA-Z][^>]*>')
_SPACE = re.compile(r'\s+')


def embedding_input(content):
    """The text sent to the embedding model for a stored problem/solution text."""
    s = _HEADING.sub(' ', content)
    s = _IMAGE.sub(' ', s)
    s = _HTML_TAG.sub(' ', s)
    return _SPACE.sub(' ', s).strip()[:MAX_INPUT_CHARS]


def has_image(content):
    return '![' in content or '<img' in content


# ── Reading the TTL files ─────────────────────────────────────────────────────

def _local_name(iri):
    return str(iri).rsplit('#', 1)[-1]


def read_ttl_tree(parent):
    """Problems of all ``*.ttl`` files below ``parent``.

    Returns ({problemid: {'texts': {lang: md}, 'solutions': {solution_iri},
    'mtime': newest source file}}, {solution_iri: {'num', 'texts', 'mtime'}},
    number of files).
    """
    problems, solutions = {}, {}
    files = sorted(Path(parent).rglob('*.ttl'))
    for path in files:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        g = Graph()
        g.parse(path, format='turtle')
        for p in g.subjects(RDF.type, ELIOZO.Problem):
            pid = str(g.value(p, ELIOZO.problemID) or _local_name(p))
            rec = problems.setdefault(pid, {'texts': {}, 'solutions': set(), 'mtime': mtime})
            rec['mtime'] = max(rec['mtime'], mtime)
            for t in g.objects(p, ELIOZO.problemText):
                if str(t).strip():
                    rec['texts'][t.language or ''] = str(t)
            rec['solutions'].update(str(s) for s in g.objects(p, ELIOZO.problemSolution))
        for s in g.subjects(RDF.type, ELIOZO.Solution):
            num = g.value(s, ELIOZO.solutionNum)
            sol = solutions.setdefault(str(s), {'num': None, 'texts': {}, 'mtime': mtime})
            sol['mtime'] = max(sol['mtime'], mtime)
            if num is not None:
                sol['num'] = str(num)
            for t in g.objects(s, ELIOZO.solutionText):
                if str(t).strip():
                    sol['texts'][t.language or ''] = str(t)
    return problems, solutions, len(files)


def desired_rows(rec, solutions):
    """(statement, lang, newest mtime, [(solution_iri, lang, text)]) for one problem."""
    texts = rec['texts']
    lang = PROBLEM_LANGUAGE if PROBLEM_LANGUAGE in texts else sorted(texts)[0]
    mtime = rec['mtime']
    chunks = []
    for iri in rec['solutions']:
        sol = solutions.get(iri)
        if sol is None:
            continue
        mtime = max(mtime, sol['mtime'])
        for sol_lang, sol_text in sol['texts'].items():
            if len(embedding_input(sol_text)) >= MIN_SOLUTION_CHARS:
                chunks.append((sol['num'] or '', iri, sol_lang, sol_text))
    chunks.sort(key=lambda c: (c[0].zfill(4), c[1], c[2]))
    return texts[lang], lang, mtime, [c[1:] for c in chunks]


# ── Step 1: sync TTL → tables ─────────────────────────────────────────────────

def sync(conn, problems, solutions):
    stats = dict(new=0, refreshed=0, unchanged=0, skipped_short=0, chunks=0)
    existing = {row.problem_iri: row for row in conn.execute(text(
        'SELECT id, problem_iri, content, updated_at FROM problems'))}

    for pid in sorted(problems):
        rec = problems[pid]
        if not rec['texts']:
            continue
        content, lang, mtime, chunks = desired_rows(rec, solutions)
        all_texts = sum(len(solutions[i]['texts']) for i in rec['solutions'] if i in solutions)
        stats['skipped_short'] += all_texts - len(chunks)
        stats['chunks'] += len(chunks)
        row = existing.get(pid)

        if row is None:
            problem_id = conn.execute(text(
                'INSERT INTO problems (problem_iri, content, lang, has_image) '
                'VALUES (:iri, :content, :lang, :img) RETURNING id'),
                dict(iri=pid, content=content, lang=lang, img=has_image(content))).scalar_one()
            old_chunks = {}
            stats['new'] += 1
        elif mtime > row.updated_at:
            problem_id = row.id
            # A changed statement loses its embedding; an unchanged one keeps it.
            conn.execute(text(
                'UPDATE problems SET content = :content, lang = :lang, has_image = :img, '
                'updated_at = now(), '
                'embedding = CASE WHEN content = :content THEN embedding END '
                'WHERE id = :id'),
                dict(id=problem_id, content=content, lang=lang, img=has_image(content)))
            old_chunks = {(r.solution_iri, r.lang, r.content): r.emb for r in conn.execute(text(
                'SELECT solution_iri, lang, content, embedding::text AS emb '
                'FROM solution_chunks WHERE problem_id = :id'), dict(id=problem_id))}
            conn.execute(text('DELETE FROM solution_chunks WHERE problem_id = :id'), dict(id=problem_id))
            stats['refreshed'] += 1
        else:
            stats['unchanged'] += 1
            continue

        for chunk_id, (sol_iri, sol_lang, sol_text) in enumerate(chunks):
            conn.execute(text(
                'INSERT INTO solution_chunks (problem_id, chunk_id, solution_iri, content, lang, embedding) '
                'VALUES (:pid, :cid, :iri, :content, :lang, CAST(:emb AS vector))'),
                dict(pid=problem_id, cid=chunk_id, iri=sol_iri, content=sol_text, lang=sol_lang,
                     emb=old_chunks.get((sol_iri, sol_lang, sol_text))))
    return stats


# ── Step 2: embed rows without a vector ───────────────────────────────────────

def embed_texts(client, texts):
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts, encoding_format='float')
    vectors = [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
    for v in vectors:
        if len(v) != EMBEDDING_DIM:
            raise ValueError('%s returned %d dimensions, expected %d' % (EMBEDDING_MODEL, len(v), EMBEDDING_DIM))
    return vectors


def embed_missing(engine, client, table):
    with engine.connect() as conn:
        todo = conn.execute(text('SELECT count(*) FROM %s WHERE embedding IS NULL' % table)).scalar_one()
    print('Embedding %d %s ...' % (todo, table))
    done = 0
    while True:
        with engine.begin() as conn:
            rows = conn.execute(text(
                'SELECT id, content FROM %s WHERE embedding IS NULL ORDER BY id LIMIT :n' % table),
                dict(n=BATCH)).fetchall()
            if not rows:
                break
            vectors = embed_texts(client, [embedding_input(r.content) or r.content for r in rows])
            for r, v in zip(rows, vectors):
                conn.execute(text('UPDATE %s SET embedding = CAST(:v AS vector) WHERE id = :id' % table),
                             dict(v=str(v), id=r.id))
        done += len(rows)
        print('  %d/%d' % (done, todo), flush=True)
        time.sleep(0.1)   # gentle rate-limit pause
    return done


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('parent_dir', help='directory searched recursively for *.ttl files')
    parser.add_argument('--sync-only', action='store_true', help='update the tables, do not call OpenAI')
    args = parser.parse_args(argv)

    if not Path(args.parent_dir).is_dir():
        parser.error('not a directory: %s' % args.parent_dir)

    problems, solutions, nfiles = read_ttl_tree(args.parent_dir)
    print('Read %d TTL files: %d problems, %d solutions' % (nfiles, len(problems), len(solutions)))
    if not problems:
        print('No eliozo:Problem found; nothing to do.')
        return 1

    engine = create_engine(dbenv.sqlalchemy_url())
    with engine.begin() as conn:
        stats = sync(conn, problems, solutions)
    print('Sync: {new} new, {refreshed} refreshed, {unchanged} unchanged problems; '
          '{chunks} solution texts kept, {skipped_short} skipped as too short'.format(**stats))

    if not args.sync_only:
        client = OpenAI(timeout=60.0, max_retries=5)   # reads OPENAI_API_KEY (loaded by dbenv)
        for table in ('problems', 'solution_chunks'):
            embed_missing(engine, client, table)

    with engine.connect() as conn:
        for table in ('problems', 'solution_chunks'):
            total, embedded = conn.execute(text(
                'SELECT count(*), count(embedding) FROM %s' % table)).one()
            print('%-16s %5d rows, %5d with embedding' % (table, total, embedded))
    return 0


if __name__ == '__main__':
    sys.exit(main())
