"""Dump the problem index (tables and embeddings) to a portable pg_dump file.

Usage:
    python pg_export_problems.py [-o FILE] [--mode auto|native|docker] [--container NAME]

Writes a ``pg_dump --format=custom`` file with the tables ``problems``,
``solution_chunks`` and ``alembic_version`` (schema, data, HNSW indexes;
the vector values travel as ordinary column data). Owners and grants are left
out so it restores under any user name. Works the same on the Ubuntu server
(native PostgreSQL) and on a Windows/macOS workstation (Docker); restore it with
``pg_import_problems.py``. Moving the file between machines is up to you.
"""

import argparse
import os
import sys
from datetime import datetime

from pgtools import TABLES, Postgres, add_arguments, counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('-o', '--output',
                        default='eliozo-problems-%s.dump' % datetime.now().strftime('%Y%m%d-%H%M'),
                        help='dump file to write (default: eliozo-problems-<timestamp>.dump)')
    add_arguments(parser)
    args = parser.parse_args(argv)

    pg = Postgres(args.mode, args.container)
    print('Exporting:', counts(pg))
    options = ['--format=custom', '--no-owner', '--no-privileges']
    for table in TABLES:
        options += ['--table', table]

    output = os.path.abspath(args.output)
    if pg.mode == 'docker':
        inside = '/tmp/eliozo-problems-export.dump'
        pg.run('pg_dump', *options, '--file', inside)
        pg.docker('cp', '%s:%s' % (pg.container, inside), output)
        pg.docker('exec', pg.container, 'rm', '-f', inside)
    else:
        pg.run('pg_dump', *options, '--file', output)

    size = os.path.getsize(output) if os.path.exists(output) else 0
    if size == 0:
        sys.exit('ERROR: %s is missing or empty' % output)
    print('Wrote %s (%.1f MB)' % (output, size / 1e6))
    return 0


if __name__ == '__main__':
    sys.exit(main())
