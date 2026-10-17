"""Restore a dump made by ``pg_export_problems.py``, replacing the problem index.

Usage:
    python pg_import_problems.py FILE [--yes] [--mode auto|native|docker] [--container NAME]

DROPS and recreates ``problems``, ``solution_chunks`` and ``alembic_version``
in the target database (one transaction: on any error nothing changes), then
loads the dumped rows, embeddings included, so nothing has to be re-embedded.
The target database must already exist with the ``vector`` extension (server:
``eliozo-setup/scripts/setup-postgresql.sh``; Docker: ``alembic upgrade head``
once). Restored objects are owned by the DB_USER of ``.env``.
"""

import argparse
import os
import sys

from pgtools import Postgres, add_arguments, counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('dump', help='file written by pg_export_problems.py')
    parser.add_argument('--yes', action='store_true', help='do not ask for confirmation')
    add_arguments(parser)
    args = parser.parse_args(argv)

    dump = os.path.abspath(args.dump)
    if not os.path.isfile(dump) or os.path.getsize(dump) == 0:
        sys.exit('ERROR: %s is missing or empty' % dump)

    pg = Postgres(args.mode, args.container)
    if pg.query("SELECT count(*) FROM pg_extension WHERE extname = 'vector'") != '1':
        sys.exit('ERROR: extension "vector" is not installed in database %s; '
                 'create it first (see the docstring)' % pg.s['name'])
    has_tables = pg.query("SELECT to_regclass('public.problems') IS NOT NULL") == 't'
    if has_tables:
        print('Current contents:', counts(pg))
    if not args.yes:
        answer = input('Replace the problem tables in %r with %s? [y/N] ' % (pg.s['name'], dump))
        if answer.strip().lower() not in ('y', 'yes'):
            print('Aborted.')
            return 1

    options = ['--clean', '--if-exists', '--no-owner', '--no-privileges',
               '--single-transaction', '--exit-on-error']
    if pg.mode == 'docker':
        inside = '/tmp/eliozo-problems-import.dump'
        pg.docker('cp', dump, '%s:%s' % (pg.container, inside))
        try:
            pg.run('pg_restore', *options, inside)
        finally:
            pg.docker('exec', pg.container, 'rm', '-f', inside)
    else:
        pg.run('pg_restore', *options, dump)

    print('Restored:', counts(pg))
    return 0


if __name__ == '__main__':
    sys.exit(main())
