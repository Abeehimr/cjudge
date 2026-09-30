"""M5 gate against a disposable database; never changes real lab data."""
import os
from pathlib import Path
import secrets
import tempfile

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from cjudge import identity, labs, tasks, submissions


def checks() -> None:
    with identity.engine().connect() as conn:
        names = sa.inspect(conn).get_table_names()
        assert all(table.name in names for table in submissions.TABLES)
        assert 'compiler_feedback' in {column['name'] for column in sa.inspect(conn).get_columns('labs')}
    print('PASS: M5 schema and migrations')


def main() -> None:
    database = 'submission_gate_' + secrets.token_hex(8)
    root_url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(root_url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
    os.environ['DATABASE_URL'] = root_url.set(database=database).render_as_string(hide_password=False)
    try:
        command.upgrade(Config('alembic.ini'), 'head')
        with tempfile.TemporaryDirectory() as directory:
            os.environ['CJUDGE_SUBMISSION_FILES'] = directory
            checks()
    finally:
        identity.engine().dispose()
        identity.engine.cache_clear()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
