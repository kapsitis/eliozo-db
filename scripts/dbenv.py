"""Connection settings for the scripts in this directory, read from ``.env``.

Standard library only, so that ``pg_export_problems.py`` and
``pg_import_problems.py`` run with a bare Python on any machine (Windows
included). The file is ``eliozo-db/.env`` unless ``ELIOZO_ENV_FILE`` names
another; like in the Flask app, values in the file win over variables already
in the environment (a stale exported OPENAI_API_KEY must not shadow the file).
"""

import os
from pathlib import Path

DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / '.env'


def env_file():
    return Path(os.environ.get('ELIOZO_ENV_FILE') or DEFAULT_ENV_FILE)


def load_env():
    """Read the dotenv file into ``os.environ``; returns its path (None if missing)."""
    path = env_file()
    if not path.is_file():
        return None
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key.startswith('export '):
            key = key[len('export '):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        os.environ[key] = value
    return path


def db_settings():
    """{'host', 'port', 'name', 'user', 'password'} from DB_* (after ``load_env``)."""
    load_env()
    missing = [k for k in ('DB_NAME', 'DB_USER', 'DB_PASSWORD') if not os.environ.get(k)]
    if missing:
        raise SystemExit('missing in %s: %s' % (env_file(), ', '.join(missing)))
    return {
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': os.environ.get('DB_PORT', '5432'),
        'name': os.environ['DB_NAME'],
        'user': os.environ['DB_USER'],
        'password': os.environ['DB_PASSWORD'],
    }


def sqlalchemy_url():
    """A psycopg 3 SQLAlchemy URL (needs SQLAlchemy installed)."""
    from sqlalchemy.engine import URL
    s = db_settings()
    return URL.create('postgresql+psycopg', username=s['user'], password=s['password'],
                      host=s['host'], port=int(s['port']), database=s['name'])
