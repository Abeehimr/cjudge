"""Versioned protected ZIP snapshots and separate, retryable permanent deletion."""
import base64
import hashlib
import json
import os
from pathlib import Path
import zipfile
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from pydantic import Field
import sqlalchemy as sa
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from cjudge import identity, labs, tasks, submissions as store
from cjudge.identity.api import admin, admin_write, StrictModel
from cjudge.labs.api import admin_router, StopInput
from cjudge.labs import files as pdf_files
from cjudge.labs.exports import final, sheet
from cjudge.labs.release import revision_ids
from cjudge.submissions import files as source_files, review
from cjudge.submissions.api import transaction
from cjudge.tasks.api import json_input

exports = sa.Table('lab_exports', identity.metadata,
    sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('lab_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False), sa.Column('snapshot_digest', sa.String(64), nullable=False),
    sa.Column('sha256', sa.String(64), nullable=False), sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
cleanup_files = sa.Table('lab_cleanup_files', identity.metadata,
    sa.Column('lab_id', sa.Uuid(), primary_key=True), sa.Column('kind', sa.String(16), primary_key=True),
    sa.Column('artifact_id', sa.Uuid(), primary_key=True))


def root() -> Path:
    return Path(os.getenv('CJUDGE_EXPORT_FILES', '/var/lib/cjudge-exports'))


def encoded(value):
    if isinstance(value, bytes):
        return {'base64': base64.b64encode(value).decode('ascii')}
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    raise TypeError('Unsupported archive value')


def json_bytes(value) -> bytes:
    return json.dumps(value, default=encoded, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def rows(conn: sa.Connection, table, condition) -> list[dict]:
    return [dict(row) for row in conn.execute(sa.select(table).where(condition).order_by(*table.primary_key.columns)).mappings()]


def snapshot(conn: sa.Connection, lab: dict) -> dict:
    lab_id = lab['id']
    submissions = rows(conn, store.submissions, store.submissions.c.lab_id == lab_id)
    ids = [row['id'] for row in submissions]
    attempts = rows(conn, store.attempts, store.attempts.c.submission_id.in_(ids))
    runs = rows(conn, store.runs, store.runs.c.submission_id.in_(ids))
    batches = rows(conn, store.batches, store.batches.c.lab_id == lab_id)
    roster = [dict(row) for row in conn.execute(sa.select(identity.accounts.c.id, identity.accounts.c.roll_number,
        identity.accounts.c.name, labs.enrollments.c.frozen, labs.enrollments.c.freeze_reason,
        labs.enrollments.c.cancelled, labs.enrollments.c.cancel_reason)
        .join(labs.enrollments, labs.enrollments.c.account_id == identity.accounts.c.id)
        .where(labs.enrollments.c.lab_id == lab_id).order_by(identity.accounts.c.id)).mappings()]
    # Export audit entries do not change grading evidence or invalidate their own receipts.
    audits = [dict(row) for row in conn.execute(sa.select(identity.audit_events).where(
        identity.audit_events.c.detail['lab_id'].as_string() == str(lab_id),
        ~identity.audit_events.c.action.in_(['lab_export_generated', 'lab_export_downloaded', 'lab_marks_exported']))
        .order_by(identity.audit_events.c.id)).mappings()]
    # ponytail: snapshot metadata loads retained history; paginate/spool if lab histories outgrow memory.
    return dict(lab=lab, roster=roster, assignments=rows(conn, labs.assignments, labs.assignments.c.lab_id == lab_id),
        pdfs=rows(conn, labs.pdfs, labs.pdfs.c.lab_id == lab_id),
        announcements=rows(conn, labs.announcements, labs.announcements.c.lab_id == lab_id),
        revisions=rows(conn, tasks.revisions, tasks.revisions.c.id.in_(revision_ids(conn, lab_id))),
        submissions=submissions, jobs=rows(conn, store.jobs, store.jobs.c.submission_id.in_(ids)), attempts=attempts, runs=runs,
        case_results=rows(conn, store.cases, store.cases.c.run_id.in_([row['id'] for row in runs])),
        reviews=rows(conn, store.reviews, store.reviews.c.submission_id.in_(ids)), corrections=batches,
        correction_members=rows(conn, store.members, store.members.c.batch_id.in_([row['id'] for row in batches])),
        marks=review.marks(conn, lab_id), audits=audits)


def file_hash(path: Path) -> tuple[str, int]:
    with path.open('rb') as file:
        size = os.fstat(file.fileno()).st_size
        return hashlib.file_digest(file, 'sha256').hexdigest(), size


def build(key: UUID, data: dict, csv_data: bytes) -> tuple[str, int]:
    path = root() / f'{key}.zip'
    manifest = {'format': 'cjudge-lab', 'version': 1, 'lab_id': str(data['lab']['id']),
        'lab_version': data['lab']['version'], 'snapshot_digest': digest(data),
        'generated_at': identity.now().isoformat(), 'entries': []}
    def add(archive, name: str, content: bytes):
        archive.writestr(name, content)
        manifest['entries'].append({'path': name, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    try:
        with path.open('xb') as file:
            os.fchmod(file.fileno(), 0o400)
            with zipfile.ZipFile(file, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                add(archive, 'snapshot.json', json_bytes(data))
                add(archive, 'marks.csv', csv_data)
                for row in data['pdfs']:
                    with (pdf_files.FILES / f'{row["id"]}.pdf').open('rb') as pdf:
                        content = pdf.read(pdf_files.MAX_PDF + 1)
                    if len(content) != row['size']:
                        raise OSError('PDF integrity check failed')
                    pdf_files.validate_pdf(content)
                    add(archive, f'pdfs/{row["id"]}.pdf', content)
                for row in data['submissions']:
                    add(archive, f'sources/{row["id"]}.c', source_files.read(row))
                for row in data['revisions']:
                    pairs = tasks.load_cases(row['cases_key'])
                    if len(pairs) != row['case_count']:
                        raise OSError('Task case count mismatch')
                    for number, (input_bytes, answer) in enumerate(pairs, 1):
                        add(archive, f'revisions/{row["id"]}/cases/{number}.in', input_bytes)
                        add(archive, f'revisions/{row["id"]}/cases/{number}.out', answer)
                    add(archive, f'revisions/{row["id"]}/statement.md', row['config']['statement'].encode())
                    add(archive, f'revisions/{row["id"]}/config.json', json_bytes(row['config']))
                archive.writestr('manifest.json', json_bytes(manifest))
            file.flush(); os.fsync(file.fileno())
        verify(path, manifest)
        directory = os.open(root(), os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
        return file_hash(path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def verify(path: Path, manifest: dict) -> None:
    with zipfile.ZipFile(path) as archive:
        expected = {entry['path'] for entry in manifest['entries']} | {'manifest.json'}
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise OSError('Archive entries mismatch')
        for entry in manifest['entries']:
            content = archive.read(entry['path'])
            if len(content) != entry['size'] or hashlib.sha256(content).hexdigest() != entry['sha256']:
                raise OSError('Archive integrity check failed')


@admin_router.post('/{lab_id}/exports', status_code=201)
async def export_lab(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, StopInput)
    if not body.reason.strip():
        raise HTTPException(400, 'Reason required')
    def perform():
        with transaction() as conn:
            # Every writer of lab evidence takes the lab lock; disk work happens after it is released.
            lab = labs.find(conn, lab_id, body.version)
            final(conn, lab)
            data = snapshot(conn, lab); csv_data = sheet(conn, lab)
        key = uuid4()
        try:
            checksum, size = build(key, data, csv_data)
            with transaction() as conn:
                current = labs.find(conn, lab_id, body.version)
                if digest(snapshot(conn, current)) != digest(data):
                    raise labs.LabError(409, 'Lab evidence changed during export; regenerate the archive')
                conn.execute(sa.insert(exports).values(id=key, lab_id=lab_id, version=body.version,
                    snapshot_digest=digest(data), sha256=checksum, size=size))
                identity.audit(conn, 'lab_export_generated', actor['id'], detail={'lab_id': str(lab_id),
                    'export_id': str(key), 'reason': body.reason.strip(), 'sha256': checksum})
            return {'id': key, 'sha256': checksum, 'size': size, 'version': body.version}
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(503, 'Archive unavailable; no successful export recorded') from exc
        # Keep an artifact after uncertain DB commits; UUID paths are private and harmless.
    return await run_in_threadpool(perform)


@admin_router.get('/{lab_id}/exports/{export_id}')
def download_export(lab_id: UUID, export_id: UUID, actor: dict = Depends(admin)):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        row = conn.execute(sa.select(exports).where(exports.c.id == export_id, exports.c.lab_id == lab_id)).mappings().first()
        if not row:
            raise HTTPException(404, 'Export not found')
        path = root() / f'{export_id}.zip'
        if file_hash(path) != (row['sha256'], row['size']):
            raise HTTPException(503, 'Archive integrity check failed')
        identity.audit(conn, 'lab_export_downloaded', actor['id'], detail={'lab_id': str(lab_id), 'export_id': str(export_id)})
    return FileResponse(path, media_type='application/zip', filename=f'{lab_id}-archive-v1.zip',
        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


class DeleteInput(StopInput):
    export_id: UUID
    title: str = Field(max_length=160)
    saved_copy: bool


def cleanup(lab_id: UUID) -> int:
    roots = {'source': (source_files.root(), '.c'), 'pdf': (pdf_files.FILES, '.pdf'), 'export': (root(), '.zip')}
    with transaction() as conn:
        pending = rows(conn, cleanup_files, cleanup_files.c.lab_id == lab_id)
        for row in pending:
            directory, suffix = roots[row['kind']]
            try: (directory / f'{row["artifact_id"]}{suffix}').unlink(missing_ok=True)
            except OSError: continue
            conn.execute(sa.delete(cleanup_files).where(cleanup_files.c.lab_id == lab_id,
                cleanup_files.c.kind == row['kind'], cleanup_files.c.artifact_id == row['artifact_id']))
        return conn.execute(sa.select(sa.func.count()).select_from(cleanup_files).where(cleanup_files.c.lab_id == lab_id)).scalar_one()


@admin_router.delete('/{lab_id}')
async def delete_lab(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, DeleteInput)
    def perform():
        from cjudge.judging import queue
        with transaction() as conn:
            lab = labs.find(conn, lab_id, body.version)
            if not lab['archived_at'] or not body.saved_copy or body.title != lab['title'] or not body.reason.strip():
                raise labs.LabError(400, 'Deletion requires an archived lab, saved-copy acknowledgment, matching title and reason')
            receipt = conn.execute(sa.select(exports).where(exports.c.id == body.export_id,
                exports.c.lab_id == lab_id)).mappings().first()
            if not receipt or receipt['version'] != lab['version'] or receipt['snapshot_digest'] != digest(snapshot(conn, lab)):
                raise labs.LabError(409, 'Generate a current archive before deletion')
            if file_hash(root() / f'{body.export_id}.zip') != (receipt['sha256'], receipt['size']):
                raise labs.LabError(503, 'Archive integrity check failed')
            queue.scheduler_lock(conn)
            source_files.lock(conn)
            ids = list(conn.execute(sa.select(store.submissions.c.id).where(store.submissions.c.lab_id == lab_id)).scalars())
            run_ids = list(conn.execute(sa.select(store.runs.c.id).where(store.runs.c.submission_id.in_(ids))).scalars())
            batch_ids = list(conn.execute(sa.select(store.batches.c.id).where(store.batches.c.lab_id == lab_id)).scalars())
            artifacts = [('source', key) for key in ids]
            artifacts += [('pdf', key) for key in conn.execute(sa.select(labs.pdfs.c.id).where(labs.pdfs.c.lab_id == lab_id)).scalars()]
            artifacts += [('export', key) for key in conn.execute(sa.select(exports.c.id).where(exports.c.lab_id == lab_id)).scalars()]
            if artifacts:
                conn.execute(sa.insert(cleanup_files), [dict(lab_id=lab_id, kind=kind, artifact_id=key) for kind, key in artifacts])
            conn.execute(sa.delete(store.members).where(store.members.c.batch_id.in_(batch_ids)))
            conn.execute(sa.delete(store.cases).where(store.cases.c.run_id.in_(run_ids)))
            conn.execute(sa.delete(store.reviews).where(store.reviews.c.submission_id.in_(ids)))
            conn.execute(sa.delete(store.jobs).where(store.jobs.c.submission_id.in_(ids)))
            conn.execute(sa.delete(store.runs).where(store.runs.c.submission_id.in_(ids)))
            conn.execute(sa.delete(store.attempts).where(store.attempts.c.submission_id.in_(ids)))
            conn.execute(sa.delete(store.batches).where(store.batches.c.lab_id == lab_id))
            conn.execute(sa.select(sa.func.set_config('cjudge.delete_lab', str(lab_id), True)))
            conn.execute(sa.delete(store.submissions).where(store.submissions.c.lab_id == lab_id))
            for table in (labs.assignments, labs.enrollments, labs.pdfs, labs.announcements, exports):
                conn.execute(sa.delete(table).where(table.c.lab_id == lab_id))
            conn.execute(sa.delete(labs.labs).where(labs.labs.c.id == lab_id))
            identity.audit(conn, 'lab_permanently_deleted', actor['id'], detail={'lab_id': str(lab_id),
                'title': lab['title'], 'export_id': str(body.export_id), 'archive_sha256': receipt['sha256'], 'reason': body.reason.strip()})
            labs.notify(conn, lab_id=lab_id)
        return {'cleanup_pending': cleanup(lab_id)}
    return await run_in_threadpool(perform)


@admin_router.post('/{lab_id}/cleanup')
def retry_cleanup(lab_id: UUID, actor: dict = Depends(admin_write)):
    result = cleanup(lab_id)
    with transaction() as conn:
        identity.audit(conn, 'lab_cleanup_retried', actor['id'], detail={'lab_id': str(lab_id), 'pending': result})
    return {'cleanup_pending': result}
