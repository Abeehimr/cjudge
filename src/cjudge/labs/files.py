"""Durable lab PDF versions. Student downloads are served only after authorization."""
import os
from pathlib import Path
import re
from uuid import UUID, uuid4

import sqlalchemy as sa

from cjudge import identity, labs

FILES = Path(os.getenv('CJUDGE_LAB_FILES', '/var/lib/cjudge-labs'))
MAX_PDF = 20 * 1024 * 1024
MAX_ACTIVE = 10


def validate_pdf(data: bytes) -> None:
    if len(data) > MAX_PDF:
        raise labs.LabError(413, 'PDF exceeds 20 MiB')
    # File identification only: PDFs are never executed or parsed on the server.
    if not re.match(rb'%PDF-[12]\.[0-9]', data) or b'%%EOF' not in data[-1024:]:
        raise labs.LabError(400, 'Upload a PDF with a valid header and end marker')


def save(data: bytes) -> UUID:
    validate_pdf(data)
    key = uuid4()
    try:
        with (FILES / f'{key}.pdf').open('xb') as file:
            os.fchmod(file.fileno(), 0o400)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        directory = os.open(FILES, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise labs.LabError(503, 'PDF storage unavailable') from exc
    return key


def upload(conn: sa.Connection, lab: dict, data: bytes, name: str, actor: UUID, replaces: UUID | None = None) -> dict:
    state = labs.phase(lab, labs.now(conn))
    if state == 'Ended' or lab['first_released_at']:
        raise labs.LabError(409, 'Reopen the lab before changing PDFs')
    if replaces:
        current = conn.execute(sa.select(labs.pdfs.c.id).where(labs.pdfs.c.id == replaces,
            labs.pdfs.c.lab_id == lab['id'], labs.pdfs.c.active)).first()
        if not current:
            raise labs.LabError(404, 'Current PDF not found')
    elif conn.execute(sa.select(sa.func.count()).select_from(labs.pdfs).where(
            labs.pdfs.c.lab_id == lab['id'], labs.pdfs.c.active)).scalar_one() >= MAX_ACTIVE:
        raise labs.LabError(400, 'At most 10 active PDFs allowed')
    key = save(data)
    if replaces:
        conn.execute(sa.update(labs.pdfs).where(labs.pdfs.c.id == replaces).values(active=False))
    conn.execute(sa.insert(labs.pdfs).values(id=key, lab_id=lab['id'], name=name, size=len(data), replaces_id=replaces))
    return labs.changed(conn, lab, actor, 'lab_pdf_uploaded',
        message=f'Lab PDF {"replaced" if replaces else "added"}: {name}')


def remove(conn: sa.Connection, lab: dict, pdf_id: UUID, actor: UUID) -> dict:
    labs.setup_open(lab, labs.now(conn))
    current = conn.execute(sa.select(labs.pdfs).where(labs.pdfs.c.id == pdf_id,
        labs.pdfs.c.lab_id == lab['id'], labs.pdfs.c.active)).mappings().first()
    if not current:
        raise labs.LabError(404, 'Current PDF not found')
    remaining = conn.execute(sa.select(sa.func.count()).select_from(labs.pdfs).where(
        labs.pdfs.c.lab_id == lab['id'], labs.pdfs.c.active, labs.pdfs.c.id != pdf_id)).scalar_one()
    if lab['starts_at'] and not remaining and any(not row['config']['statement'].strip()
                                                for row in labs.task_rows(conn, lab['id'])):
        raise labs.LabError(400, 'Scheduled lab still needs a PDF or Markdown for every task')
    conn.execute(sa.update(labs.pdfs).where(labs.pdfs.c.id == pdf_id).values(active=False))
    return labs.changed(conn, lab, actor, 'lab_pdf_removed', message=f'Lab PDF removed: {current["name"]}')


def read(conn: sa.Connection, lab_id: UUID, pdf_id: UUID, *, active_only: bool) -> bytes:
    query = sa.select(labs.pdfs.c.size).where(labs.pdfs.c.id == pdf_id, labs.pdfs.c.lab_id == lab_id)
    if active_only:
        query = query.where(labs.pdfs.c.active)
    size = conn.execute(query).scalar_one_or_none()
    if size is None:
        raise labs.LabError(404, 'PDF not found')
    try:
        with (FILES / f'{pdf_id}.pdf').open('rb') as file:
            data = file.read(MAX_PDF + 1)
        if len(data) != size:
            raise OSError('PDF size mismatch')
        return data
    except OSError as exc:
        raise labs.LabError(503, 'PDF unavailable') from exc
