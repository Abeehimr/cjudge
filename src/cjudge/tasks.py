"""Task persistence. Case sets are durable and immutable before DB references them."""

import os
from pathlib import Path
from uuid import UUID, uuid4
import zipfile

import sqlalchemy as sa

from cjudge.identity import metadata
from cjudge.task_cases import parse_zip, validate_cases

ARTIFACTS = Path(os.getenv('CJUDGE_TASK_FILES', '/var/lib/cjudge-tasks'))
tasks = sa.Table('tasks', metadata,
    sa.Column('id', sa.Uuid(), primary_key=True),
    sa.Column('version', sa.Integer()),
    sa.Column('config', sa.JSON()),
    sa.Column('cases_key', sa.Uuid()),
    sa.Column('case_count', sa.Integer()),
    sa.Column('created_at', sa.DateTime(timezone=True)))
revisions = sa.Table('task_revisions', metadata,
    sa.Column('id', sa.Uuid(), primary_key=True),
    sa.Column('task_id', sa.Uuid()),
    sa.Column('number', sa.Integer()),
    sa.Column('draft_version', sa.Integer()),
    sa.Column('config', sa.JSON()),
    sa.Column('cases_key', sa.Uuid()),
    sa.Column('case_count', sa.Integer()),
    sa.Column('created_at', sa.DateTime(timezone=True)))


def save_cases(cases: list[tuple[bytes, bytes]]) -> UUID:
    validate_cases(cases)
    if not cases:
        raise ValueError('Cannot store an empty case set')
    key = uuid4()
    path = ARTIFACTS / f'{key}.zip'
    # Paths are server-generated; no archive extraction or user-supplied paths.
    with path.open('xb') as file:
        os.fchmod(file.fileno(), 0o400)
        with zipfile.ZipFile(file, 'w', zipfile.ZIP_STORED) as archive:
            for number, (input_bytes, answer) in enumerate(cases, 1):
                archive.writestr(f'{number}.in', input_bytes)
                archive.writestr(f'{number}.out', answer)
        file.flush()
        os.fsync(file.fileno())
    directory = os.open(ARTIFACTS, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    # Unreferenced files after an interrupted transaction are harmless; never risk
    # deleting a file whose DB commit may have succeeded during a connection failure.
    return key


def load_cases(key: UUID | None) -> list[tuple[bytes, bytes]]:
    if key is None:
        return []
    return parse_zip((ARTIFACTS / f'{UUID(str(key))}.zip').read_bytes())


def case_summary(cases: list[tuple[bytes, bytes]]) -> list[dict]:
    return [{'number': number, 'input_bytes': len(input_bytes), 'answer_bytes': len(answer)}
            for number, (input_bytes, answer) in enumerate(cases, 1)]
