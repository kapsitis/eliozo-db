"""Run the PostgreSQL client tools against the eliozo database, natively or in Docker.

Shared by ``pg_export_problems.py`` and ``pg_import_problems.py``. Standard
library only. Two ways to reach the database:

* ``native`` -- ``pg_dump``/``pg_restore``/``psql`` on PATH talk to DB_HOST:DB_PORT
  (the Ubuntu server, where PostgreSQL is a system service);
* ``docker`` -- the tools inside the PostgreSQL container are used through
  ``docker exec``, files are moved with ``docker cp`` (Windows/macOS
  workstations, container ``eliozo-db`` from ``docker-compose.yml``).

``auto`` picks ``docker`` when that container is running, else ``native``.
The password is passed in the PGPASSWORD environment variable, never on a
command line. With an empty DB_PASSWORD and DB_HOST=/var/run/postgresql the
native tools use the Unix socket and peer authentication (the Jenkins job).
"""

import os
import shutil
import subprocess
import sys

import dbenv

DEFAULT_CONTAINER = 'eliozo-db'
# Tables that make up the problem index. alembic_version comes along so that
# the target database knows which migration the restored schema is at.
TABLES = ('problems', 'solution_chunks', 'alembic_version')


def add_arguments(parser):
    parser.add_argument('--mode', choices=('auto', 'native', 'docker'), default='auto',
                        help='how to reach PostgreSQL (default: auto)')
    parser.add_argument('--container', default=DEFAULT_CONTAINER,
                        help='Docker container name for --mode docker (default: %(default)s)')


def container_running(name):
    if not shutil.which('docker'):
        return False
    r = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', name],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == 'true'


class Postgres:
    def __init__(self, mode, container):
        self.s = dbenv.db_settings()
        if mode == 'auto':
            mode = 'docker' if container_running(container) else 'native'
        self.mode, self.container = mode, container
        if mode == 'docker' and not container_running(container):
            sys.exit('Docker container %r is not running (docker compose up -d)' % container)
        if mode == 'native':
            for tool in ('pg_dump', 'pg_restore', 'psql'):
                if not shutil.which(tool):
                    sys.exit('%s not found on PATH (Ubuntu: apt install postgresql-client-16)' % tool)
        self.env = dict(os.environ)
        if self.s['password']:
            self.env['PGPASSWORD'] = self.s['password']
        print('PostgreSQL via %s%s, database %s, user %s' % (
            mode, ' (container %s)' % container if mode == 'docker' else
            ' (%s:%s)' % (self.s['host'], self.s['port']), self.s['name'], self.s['user']))

    def command(self, tool, *args):
        """argv for running ``tool`` with connection options against the database."""
        conn = ['-U', self.s['user'], '-d', self.s['name']]
        if self.mode == 'docker':
            # Inside the container: the local socket, user/db as in .env.
            return ['docker', 'exec', '-i', '-e', 'PGPASSWORD', self.container, tool] + conn + list(args)
        return [tool, '-h', self.s['host'], '-p', str(self.s['port'])] + conn + list(args)

    def run(self, tool, *args, capture=False):
        argv = self.command(tool, *args)
        r = subprocess.run(argv, env=self.env, capture_output=capture, text=capture)
        if r.returncode != 0:
            if capture:
                sys.stderr.write(r.stderr)
            sys.exit('%s failed (exit %d)' % (tool, r.returncode))
        return r.stdout if capture else None

    def query(self, sql):
        return self.run('psql', '-X', '-A', '-t', '-c', sql, capture=True).strip()

    def docker(self, *args):
        r = subprocess.run(['docker'] + list(args))
        if r.returncode != 0:
            sys.exit('docker %s failed (exit %d)' % (args[0], r.returncode))


def counts(pg):
    return pg.query('SELECT (SELECT count(*) FROM problems) || \' problems (\' || '
                    '(SELECT count(embedding) FROM problems) || \' embedded), \' || '
                    '(SELECT count(*) FROM solution_chunks) || \' solution chunks (\' || '
                    '(SELECT count(embedding) FROM solution_chunks) || \' embedded)\'')
