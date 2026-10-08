"""Per-lab browser authorization, with session revalidation under enrollment locks."""
import ipaddress
import os
import secrets
import socket
from uuid import UUID

from fastapi import Request
import sqlalchemy as sa

from cjudge import identity, labs

COOKIE_DAYS = 365


def cookie_name(lab_id: UUID) -> str:
    return 'cjudge_lab_' + lab_id.hex


def client_ip(request: Request) -> str:
    peer = str(ipaddress.ip_address(request.client.host))
    header = request.headers.get('x-real-ip')
    if not header:
        return peer
    try:
        addresses = {str(ipaddress.ip_address(info[4][0])) for info in socket.getaddrinfo(
            os.getenv('CJUDGE_PROXY_HOST', 'web'), None, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise labs.LabError(503, 'Trusted proxy address unavailable') from exc
    if peer not in addresses:
        return peer
    try:
        return str(ipaddress.ip_address(header))
    except ValueError as exc:
        raise labs.LabError(400, 'Invalid client IP') from exc


def access(conn: sa.Connection, lab: dict, account_id: UUID, session_token: str | None,
           token: str | None, ip: str, *, enter: bool = False, readonly: bool = False) -> tuple[dict, str | None]:
    readonly = readonly and not enter
    row = labs.enrollment(conn, lab['id'], account_id, lock=not readonly)
    if readonly and (row['binding_hash'] is None or row['last_ip'] != ip):
        # IP changes still use the original lab-before-enrollment write locks.
        lab.update(labs.find(conn, lab['id'], shared=True))
        row = labs.enrollment(conn, lab['id'], account_id)
        readonly = False
    timestamp = labs.now(conn)
    session = conn.execute(sa.select(identity.sessions.c.token_hash).where(
        identity.sessions.c.account_id == account_id,
        identity.sessions.c.token_hash == identity.token_digest(session_token or ''),
        identity.sessions.c.expires_at > timestamp)).first()
    if not session:
        raise labs.LabError(401, 'Login required')
    if lab['starts_at'] is None or timestamp < lab['starts_at']:
        raise labs.LabError(403, 'Lab materials are hidden until start')
    new_token = None
    if row['binding_hash'] is None:
        if not enter:
            raise labs.LabError(423, 'Enter lab to bind this browser')
        new_token = secrets.token_urlsafe(32)
        conn.execute(sa.update(labs.enrollments).where(labs.enrollments.c.lab_id == lab['id'],
            labs.enrollments.c.account_id == account_id).values(binding_hash=identity.token_digest(new_token),
            bound_ip=ip, last_ip=ip, bound_at=timestamp, ip_changed=False))
        identity.audit(conn, 'lab_browser_bound', subject_id=account_id, detail={'lab_id': str(lab['id']), 'ip': ip})
    elif not token or len(token) > 128 or not secrets.compare_digest(row['binding_hash'], identity.token_digest(token)):
        raise labs.LabError(423, 'Browser binding lost or used elsewhere; ask admin to release it')
    elif lab['strict_ip'] and row['bound_ip'] != ip:
        raise labs.LabError(423, 'Client IP changed; ask admin to release browser binding')
    elif row['last_ip'] != ip:
        conn.execute(sa.update(labs.enrollments).where(labs.enrollments.c.lab_id == lab['id'],
            labs.enrollments.c.account_id == account_id).values(last_ip=ip, ip_changed=True))
        identity.audit(conn, 'lab_ip_changed', subject_id=account_id, detail={'lab_id': str(lab['id']), 'ip': ip})
    return (row if readonly else labs.enrollment(conn, lab['id'], account_id)), new_token


def release(conn: sa.Connection, lab: dict, account_id: UUID, reason: str, actor: UUID) -> dict:
    labs.enrollment(conn, lab['id'], account_id)
    active = identity.checked_cipher(conn)
    student = conn.execute(sa.select(identity.accounts.c.id, identity.accounts.c.roll_number,
        identity.accounts.c.name).where(identity.accounts.c.id == account_id,
        identity.accounts.c.role == 'student').with_for_update()).mappings().one()
    password = identity.rotate_student_password(conn, account_id, active)
    conn.execute(sa.update(labs.enrollments).where(labs.enrollments.c.lab_id == lab['id'],
        labs.enrollments.c.account_id == account_id).values(binding_hash=None, bound_ip=None, last_ip=None,
                                                          bound_at=None, ip_changed=False))
    identity.audit(conn, 'lab_binding_released', actor, account_id, detail={'lab_id': str(lab['id']), 'reason': reason})
    labs.announce(conn, lab['id'], f'Browser binding and password reset. Ask admin for the new password, then sign in and enter the lab again. Reason: {reason}', actor, account_id)
    return {**student, 'password': password}
