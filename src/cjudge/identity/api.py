"""Identity HTTP routes. Every student management response has an explicit shape."""

from typing import Literal
from uuid import UUID
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from cryptography.fernet import InvalidToken
from pydantic import BaseModel, ConfigDict, Field
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from cjudge import identity as store
from cjudge.events import publish


router = APIRouter(prefix="/api")
COOKIE = "cjudge_session"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(StrictModel):
    identifier: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SessionOutput(StrictModel):
    id: UUID
    role: str
    roll_number: str | None
    name: str
    csrf_token: str


class StudentInput(StrictModel):
    roll_number: str
    name: str


class NameInput(StrictModel):
    name: str


class StudentOutput(StrictModel):
    id: UUID
    roll_number: str
    name: str
    active: bool


class CredentialOutput(StudentOutput):
    password: str


class CredentialSelection(StrictModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)


class RemovalInput(StrictModel):
    reason: str = Field(min_length=1, max_length=500)


class RemovalOutput(StrictModel):
    id: UUID
    roll_number: str
    name: str
    outcome: Literal["deleted", "deactivated"]


class ImportOutput(StrictModel):
    created: list[str]
    existing: list[str]
    name_mismatches: list[str]


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def same_origin(request: Request) -> None:
    expected = os.getenv("CJUDGE_PUBLIC_ORIGIN", "https://localhost:8443")
    if request.headers.get("origin") != expected:
        raise HTTPException(403, "Invalid request origin")


def current(request: Request) -> dict:
    account = store.current_session(request.cookies.get(COOKIE))
    if not account:
        raise HTTPException(401, "Login required")
    return account


def admin(account: dict = Depends(current)) -> dict:
    if account["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return account


def write_guard(request: Request, account: dict = Depends(current)) -> dict:
    same_origin(request)
    if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), account["csrf_token"]):
        raise HTTPException(403, "Invalid CSRF token")
    return account


def admin_write(account: dict = Depends(write_guard)) -> dict:
    if account["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return account


def student_row(conn: sa.Connection, account_id: UUID, *, lock: bool = False) -> dict:
    query = sa.select(store.accounts.c.id, store.accounts.c.roll_number, store.accounts.c.name,
                      store.accounts.c.active).where(store.accounts.c.id == account_id,
                                                     store.accounts.c.role == "student")
    row = conn.execute(query.with_for_update() if lock else query)
    found = row.mappings().first()
    if not found:
        raise HTTPException(404, "Student not found")
    return dict(found)


@router.post("/auth/{role}/login", response_model=SessionOutput)
def login(role: Literal["admin", "student"], body: LoginInput, request: Request, response: Response) -> dict:
    same_origin(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "JSON required")
    try:
        result = store.authenticate(role, body.identifier, body.password)
    except ValueError:
        result = None
    if not result:
        raise HTTPException(401, "Invalid credentials")
    account, token = result
    response.set_cookie(COOKIE, token, max_age=8 * 3600, secure=True, httponly=True,
                        samesite="lax", path="/")
    no_store(response)
    return account


@router.get("/auth/session", response_model=SessionOutput)
def session(response: Response, account: dict = Depends(current)) -> dict:
    no_store(response)
    return account


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, account: dict = Depends(write_guard)) -> None:
    with store.engine().begin() as conn:
        conn.execute(sa.delete(store.sessions).where(
            store.sessions.c.token_hash == store.token_digest(request.cookies[COOKIE])))
        store.audit(conn, "logout", actor_id=account["id"])
        publish(conn, account_id=account["id"])
    response.delete_cookie(COOKIE, path="/")
    no_store(response)


@router.get("/admin/students", response_model=list[StudentOutput])
def list_students(response: Response, search: str = "", state: Literal["active", "inactive", "all"] = "active",
                  account: dict = Depends(admin)) -> list[dict]:
    if len(search) > 64:
        raise HTTPException(400, "Search too long")
    query = sa.select(store.accounts.c.id, store.accounts.c.roll_number, store.accounts.c.name,
                      store.accounts.c.active)
    query = query.where(store.accounts.c.role == "student")
    if state != "all":
        query = query.where(store.accounts.c.active == (state == "active"))
    if search:
        query = query.where(sa.or_(store.accounts.c.roll_number.ilike(f"%{search}%"),
                                   store.accounts.c.name.ilike(f"%{search}%")))
    with store.engine().connect() as conn:
        no_store(response)
        return [dict(row) for row in conn.execute(query.order_by(store.accounts.c.roll_number).limit(500)).mappings()]


@router.post("/admin/students", response_model=StudentOutput, status_code=201)
def create_student(body: StudentInput, account: dict = Depends(admin_write)) -> dict:
    try:
        roll = store.normalize_roll(body.roll_number)
        name = store.normalize_name(body.name)
        with store.engine().begin() as conn:
            student_id = store.add_student(conn, roll, name)
            store.audit(conn, "student_created", account["id"], student_id)
        return {"id": student_id, "roll_number": roll, "name": name, "active": True}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "Roll number already exists") from exc
    except RuntimeError as exc:
        raise HTTPException(503, "Credentials unavailable") from exc


@router.patch("/admin/students/{account_id}", response_model=StudentOutput)
def rename_student(account_id: UUID, body: NameInput, account: dict = Depends(admin_write)) -> dict:
    try:
        name = store.normalize_name(body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with store.engine().begin() as conn:
        student_row(conn, account_id)
        conn.execute(sa.update(store.accounts).where(store.accounts.c.id == account_id).values(name=name))
        store.audit(conn, "student_renamed", account["id"], account_id)
        return student_row(conn, account_id)


@router.post("/admin/students/import", response_model=ImportOutput)
async def import_csv(request: Request, account: dict = Depends(admin_write)) -> dict:
    if request.headers.get("content-type", "").split(";")[0] != "text/csv":
        raise HTTPException(415, "CSV required")
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > 1024 * 1024:
        raise HTTPException(413, "CSV exceeds 1 MiB")
    payload = await request.body()
    try:
        rows = store.parse_csv(payload)
        return await run_in_threadpool(store.import_students, rows, account["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, "Credentials unavailable") from exc


@router.post("/admin/students/credentials", response_model=list[CredentialOutput])
def credentials(body: CredentialSelection, response: Response, account: dict = Depends(admin_write)) -> list[dict]:
    if len(body.ids) != len(set(body.ids)):
        raise HTTPException(400, "Duplicate student selection")
    try:
        with store.engine().begin() as conn:
            cipher = store.checked_cipher(conn)
            rows = conn.execute(sa.select(store.accounts.c.id, store.accounts.c.roll_number,
                                          store.accounts.c.name, store.accounts.c.active,
                                          store.accounts.c.encrypted_password)
                                .where(store.accounts.c.id.in_(body.ids), store.accounts.c.role == "student"))
            selected = [dict(row) for row in rows.mappings()]
            if len(selected) != len(body.ids):
                raise HTTPException(404, "Student not found")
            if any(not row["active"] for row in selected):
                raise HTTPException(409, "Inactive student account; reactivate it first")
            result = [{"id": row["id"], "roll_number": row["roll_number"], "name": row["name"],
                       "active": row["active"],
                       "password": cipher.decrypt(row["encrypted_password"]).decode()}
                      for row in selected]
            store.audit(conn, "credentials_accessed", account["id"],
                        detail={"student_ids": [str(row["id"]) for row in selected]})
        no_store(response)
        return result
    except (OSError, ValueError, RuntimeError, InvalidToken) as exc:
        raise HTTPException(503, "Credentials unavailable") from exc


@router.post("/admin/students/{account_id}/reset", response_model=CredentialOutput)
def reset_student(account_id: UUID, response: Response, account: dict = Depends(admin_write)) -> dict:
    try:
        with store.engine().begin() as conn:
            cipher = store.checked_cipher(conn)
            row = student_row(conn, account_id, lock=True)
            if not row["active"]:
                raise HTTPException(409, "Inactive student account; reactivate it first")
            password = store.rotate_student_password(conn, account_id, cipher)
            store.audit(conn, "student_password_reset", account["id"], account_id)
        no_store(response)
        return {**row, "password": password}
    except RuntimeError as exc:
        raise HTTPException(503, "Credentials unavailable") from exc


@router.post("/admin/students/reset", response_model=list[CredentialOutput])
def reset_students(body: CredentialSelection, response: Response, account: dict = Depends(admin_write)) -> list[dict]:
    if len(body.ids) != len(set(body.ids)):
        raise HTTPException(400, "Duplicate student selection")
    try:
        with store.engine().begin() as conn:
            cipher = store.checked_cipher(conn)
            rows = conn.execute(sa.select(store.accounts.c.id, store.accounts.c.roll_number,
                                          store.accounts.c.name, store.accounts.c.active)
                                .where(store.accounts.c.id.in_(body.ids), store.accounts.c.role == "student")
                                .order_by(store.accounts.c.id).with_for_update()).mappings().all()
            if len(rows) != len(body.ids):
                raise HTTPException(404, "Student not found")
            if any(not row["active"] for row in rows):
                raise HTTPException(409, "Inactive student account; reactivate it first")
            by_id = {row["id"]: row for row in rows}
            result = [{**by_id[account_id], "password": store.rotate_student_password(conn, account_id, cipher)}
                      for account_id in body.ids]
            store.audit(conn, "student_passwords_reset", account["id"],
                        detail={"student_ids": [str(account_id) for account_id in body.ids]})
        no_store(response)
        return result
    except RuntimeError as exc:
        raise HTTPException(503, "Credentials unavailable") from exc


@router.post("/admin/students/{account_id}/remove", response_model=RemovalOutput)
def remove_student(account_id: UUID, body: RemovalInput, response: Response,
                   actor: dict = Depends(admin_write)) -> dict:
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, "Reason required")
    from cjudge import authoring, labs, submissions
    try:
        with store.engine().begin() as conn:
            row = student_row(conn, account_id, lock=True)
            references = (
                labs.enrollments.c.account_id, submissions.submissions.c.account_id,
                labs.announcements.c.recipient_id, labs.announcements.c.author_id,
                submissions.reviews.c.deleted_by, submissions.batches.c.actor_id,
                authoring.jobs.c.actor_id,
            )
            retained = any(conn.execute(sa.select(column).where(column == account_id).limit(1)).first()
                           for column in references)
            if retained:
                if row["active"]:
                    conn.execute(sa.update(store.accounts).where(store.accounts.c.id == account_id).values(active=False))
                    conn.execute(sa.delete(store.sessions).where(store.sessions.c.account_id == account_id))
                    conn.execute(sa.update(labs.enrollments).where(labs.enrollments.c.account_id == account_id)
                        .values(binding_hash=None, bound_ip=None, last_ip=None, bound_at=None, ip_changed=False))
                    publish(conn, account_id=account_id)
                    store.audit(conn, "student_deactivated", actor["id"], account_id,
                                detail={"reason": reason})
                outcome = "deactivated"
            else:
                snapshot = {"id": str(account_id), "roll_number": row["roll_number"], "name": row["name"]}
                audits = conn.execute(sa.select(store.audit_events).where(sa.or_(
                    store.audit_events.c.actor_id == account_id,
                    store.audit_events.c.subject_id == account_id)).with_for_update()).mappings().all()
                for event in audits:
                    detail = dict(event["detail"] or {})
                    detail["deleted_account"] = snapshot
                    conn.execute(sa.update(store.audit_events).where(store.audit_events.c.id == event["id"]).values(
                        actor_id=None if event["actor_id"] == account_id else event["actor_id"],
                        subject_id=None if event["subject_id"] == account_id else event["subject_id"],
                        detail=detail))
                conn.execute(sa.delete(submissions.turns).where(submissions.turns.c.account_id == account_id))
                conn.execute(sa.delete(store.accounts).where(store.accounts.c.id == account_id))
                publish(conn, account_id=account_id)
                store.audit(conn, "student_deleted", actor["id"], detail={"reason": reason,
                                                                            "deleted_account": snapshot})
                outcome = "deleted"
        no_store(response)
        return {"id": account_id, "roll_number": row["roll_number"], "name": row["name"], "outcome": outcome}
    except IntegrityError as exc:
        raise HTTPException(409, "Account has retained records; reload and try again") from exc


@router.post("/admin/students/{account_id}/reactivate", response_model=CredentialOutput)
def reactivate_student(account_id: UUID, response: Response, actor: dict = Depends(admin_write)) -> dict:
    try:
        with store.engine().begin() as conn:
            row = student_row(conn, account_id, lock=True)
            if row["active"]:
                raise HTTPException(409, "Student account is already active")
            cipher = store.checked_cipher(conn)
            password = store.rotate_student_password(conn, account_id, cipher)
            conn.execute(sa.update(store.accounts).where(store.accounts.c.id == account_id).values(active=True))
            store.audit(conn, "student_reactivated", actor["id"], account_id)
        no_store(response)
        return {**row, "active": True, "password": password}
    except RuntimeError as exc:
        raise HTTPException(503, "Credentials unavailable") from exc
