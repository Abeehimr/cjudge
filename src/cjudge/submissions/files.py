"""Immutable bounded sources. Call save while holding the shared artifact DB lock."""
import hashlib
import os
from pathlib import Path
import re
import stat
from uuid import UUID

import sqlalchemy as sa

from cjudge import identity
from cjudge.submissions import submissions

SOURCE_BYTES = 64 * 1024
ARTIFACT_LOCK = 51001


def root() -> Path:
    return Path(os.getenv('CJUDGE_SUBMISSION_FILES', '/var/lib/cjudge-submissions'))


def validate(filename: str, source: bytes) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,157}\.c', filename):
        raise ValueError('Use a plain .c filename, at most 160 characters')
    if not 0 < len(source) <= SOURCE_BYTES or b'\x00' in source:
        raise ValueError('Source must contain 1–65536 bytes and no NUL bytes')
    return hashlib.sha256(source).hexdigest()


def lock(conn: sa.Connection) -> None:
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock_shared(ARTIFACT_LOCK)))


def save(key: UUID, source: bytes) -> None:
    path = root() / f'{key}.c'
    with path.open('xb') as file:
        os.fchmod(file.fileno(), 0o400)
        file.write(source)
        file.flush()
        os.fsync(file.fileno())
    directory = os.open(root(), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read(row: dict) -> bytes:
    fd = os.open(root() / f'{UUID(str(row["id"]))}.c', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise OSError('Invalid source artifact')
        data = file.read(SOURCE_BYTES + 1)
    if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
        raise OSError('Source integrity check failed')
    return data


def cleanup() -> int:
    # Exclusive lock waits for uploads/uncertain commits; never race an acceptance.
    with identity.engine().begin() as conn:
        conn.execute(sa.select(sa.func.pg_advisory_xact_lock(ARTIFACT_LOCK)))
        referenced = {f'{key}.c' for key in conn.execute(sa.select(submissions.c.id)).scalars()}
        removed = 0
        for path in root().glob('*.c'):
            if re.fullmatch(r'[0-9a-f-]{36}\.c', path.name) and path.name not in referenced:
                path.unlink()
                removed += 1
        return removed


if __name__ == '__main__':
    print(f'Removed {cleanup()} unreferenced sources')
