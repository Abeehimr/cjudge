"""Global accounts and sessions. Student password recovery is admin-only."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import getpass
import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import sys
from threading import BoundedSemaphore
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert


KEY_FILE = Path("/var/lib/cjudge/credentials.key")
SESSION_LIFETIME = timedelta(hours=8)
LOGIN_WINDOW = timedelta(minutes=5)
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_hasher = PasswordHasher()
_hash_slots = BoundedSemaphore(4)
metadata = sa.MetaData()
accounts = sa.Table(
    "accounts", metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("role", sa.String(7)),
    sa.Column("roll_number", sa.String(64)),
    sa.Column("name", sa.String(120)),
    sa.Column("password_hash", sa.Text()),
    sa.Column("encrypted_password", sa.LargeBinary()),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)
sessions = sa.Table(
    "sessions", metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("account_id", sa.Uuid()),
    sa.Column("csrf_token", sa.String(64)),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
)
login_attempts = sa.Table(
    "login_attempts", metadata,
    sa.Column("identifier", sa.String(72), primary_key=True),
    sa.Column("window_start", sa.DateTime(timezone=True)),
    sa.Column("failures", sa.Integer()),
)
audit_events = sa.Table(
    "audit_events", metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("actor_id", sa.Uuid()),
    sa.Column("subject_id", sa.Uuid()),
    sa.Column("action", sa.String(64)),
    sa.Column("detail", sa.JSON()),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


def now() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache
def engine() -> sa.Engine:
    return sa.create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, pool_size=5, max_overflow=5)


def cipher() -> Fernet:
    try:
        return Fernet(KEY_FILE.read_bytes().strip())
    except (OSError, ValueError) as exc:
        raise RuntimeError("Student credential key is missing or invalid") from exc


def checked_cipher(conn: sa.Connection) -> Fernet:
    active = cipher()
    stored = conn.execute(sa.select(accounts.c.encrypted_password)
                          .where(accounts.c.role == "student").limit(1)).scalar_one_or_none()
    if stored is not None:
        try:
            active.decrypt(stored)
        except InvalidToken as exc:
            raise RuntimeError("Student credential key does not match stored credentials") from exc
    return active


def init_key() -> None:
    KEY_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(Fernet.generate_key())
    if os.geteuid() == 0:
        os.chown(KEY_FILE, 10001, 10001)
    print("Credential key created. Back up the named Docker volume securely.")


def normalize_roll(value: str) -> str:
    roll = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,63}", roll):
        raise ValueError("Roll number must use 1–64 letters, digits, '.', '_', '/' or '-'")
    return roll


def normalize_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= 120 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("Name must contain 1–120 printable characters")
    return name


def generate_password() -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(12))


def hash_password(password: str) -> str:
    with _hash_slots:
        return _hasher.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        with _hash_slots:
            return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError):
        return False


@lru_cache
def dummy_hash() -> str:
    return hash_password("unused dummy password")


def audit(conn: sa.Connection, action: str, actor_id: UUID | None = None,
          subject_id: UUID | None = None, detail: dict | None = None) -> None:
    conn.execute(sa.insert(audit_events).values(actor_id=actor_id, subject_id=subject_id,
                                                action=action, detail=detail or {}))


def create_admin(password: str) -> None:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Admin password must contain 12–128 characters")
    with engine().begin() as conn:
        account_id = uuid4()
        conn.execute(sa.insert(accounts).values(id=account_id, role="admin", name="Administrator",
                                                password_hash=hash_password(password)))
        audit(conn, "admin_created", subject_id=account_id)


def reset_admin(password: str) -> None:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Admin password must contain 12–128 characters")
    with engine().begin() as conn:
        admin = conn.execute(sa.select(accounts.c.id).where(accounts.c.role == "admin")).scalar_one()
        conn.execute(sa.update(accounts).where(accounts.c.id == admin).values(password_hash=hash_password(password)))
        conn.execute(sa.delete(sessions).where(sessions.c.account_id == admin))
        audit(conn, "admin_password_reset", subject_id=admin)


def add_student(conn: sa.Connection, roll: str, name: str) -> UUID:
    student_id = uuid4()
    password = generate_password()
    active = checked_cipher(conn)
    conn.execute(sa.insert(accounts).values(id=student_id, role="student", roll_number=roll,
                                            name=name, password_hash=hash_password(password),
                                            encrypted_password=active.encrypt(password.encode())))
    return student_id


def parse_csv(payload: bytes) -> list[tuple[str, str]]:
    if len(payload) > 1024 * 1024:
        raise ValueError("CSV exceeds 1 MiB")
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig", errors="strict")), strict=True)
        if reader.fieldnames != ["roll_number", "name"]:
            raise ValueError("CSV must have roll_number,name headers")
        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        for row in reader:
            if len(rows) == 1000 or None in row or not isinstance(row.get("name"), str):
                raise ValueError("CSV has malformed rows or exceeds 1000 students")
            roll, name = normalize_roll(row["roll_number"]), normalize_name(row["name"])
            if roll in seen:
                raise ValueError(f"Duplicate roll number: {roll}")
            seen.add(roll)
            rows.append((roll, name))
        if not rows:
            raise ValueError("CSV has no students")
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("CSV must be valid UTF-8 CSV") from exc


def import_student_rows(conn: sa.Connection, rows: list[tuple[str, str]]) -> dict:
    """Find/create accounts inside the caller's transaction (including lab enrollment)."""
    created: list[str] = []
    existing: list[str] = []
    mismatched: list[str] = []
    active = checked_cipher(conn)
    for roll, name in rows:
        present = conn.execute(sa.select(accounts.c.id, accounts.c.name)
                               .where(accounts.c.roll_number == roll)).first()
        if present:
            existing.append(roll)
            if present.name != name:
                mismatched.append(roll)
        else:
            # RETURNING distinguishes a new row from a concurrent conflict.
            inserted = conn.execute(pg_insert(accounts).values(
                id=uuid4(), role="student", roll_number=roll, name=name,
                password_hash=hash_password(password := generate_password()),
                encrypted_password=active.encrypt(password.encode()),
            ).on_conflict_do_nothing(index_elements=[accounts.c.roll_number])
              .returning(accounts.c.id)).scalar_one_or_none()
            if inserted:
                created.append(roll)
            else:
                existing.append(roll)
                present = conn.execute(sa.select(accounts.c.name).where(accounts.c.roll_number == roll)).scalar_one()
                if present != name:
                    mismatched.append(roll)
    return {"created": created, "existing": existing, "name_mismatches": mismatched}


def import_students(rows: list[tuple[str, str]], actor_id: UUID) -> dict:
    with engine().begin() as conn:
        result = import_student_rows(conn, rows)
        audit(conn, "students_imported", actor_id, detail={key: len(value) for key, value in result.items()})
        return result


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(role: str, identifier: str, password: str) -> tuple[dict, str] | None:
    normalized = "ADMIN" if role == "admin" else normalize_roll(identifier)
    throttle_key = f"{role}:{normalized}"
    with engine().begin() as conn:
        conn.execute(pg_insert(login_attempts).values(identifier=throttle_key, window_start=now(), failures=0)
                     .on_conflict_do_nothing(index_elements=[login_attempts.c.identifier]))
        attempt = conn.execute(sa.select(login_attempts).where(login_attempts.c.identifier == throttle_key)
                               .with_for_update()).mappings().one()
        start = now()
        if start >= attempt["window_start"] + LOGIN_WINDOW:
            conn.execute(sa.update(login_attempts).where(login_attempts.c.identifier == throttle_key)
                         .values(window_start=start, failures=0))
            failures = 0
        else:
            failures = attempt["failures"]
        if failures >= 5:
            audit(conn, "login_throttled", detail={"identifier": throttle_key})
            return None
        query = sa.select(accounts).where(accounts.c.role == role)
        if role == "student":
            query = query.where(accounts.c.roll_number == normalized)
        elif identifier.strip().lower() != "admin":
            query = query.where(accounts.c.name == "")
        account = conn.execute(query).mappings().first()
        if not verify_password(account["password_hash"] if account else dummy_hash(), password):
            conn.execute(sa.update(login_attempts).where(login_attempts.c.identifier == throttle_key)
                         .values(failures=failures + 1))
            audit(conn, "login_failed", subject_id=account["id"] if account else None,
                  detail={"identifier": throttle_key})
            return None
        conn.execute(sa.delete(login_attempts).where(login_attempts.c.identifier == throttle_key))
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_hex(32)
        conn.execute(sa.insert(sessions).values(token_hash=token_digest(token), account_id=account["id"],
                                                csrf_token=csrf, expires_at=start + SESSION_LIFETIME))
        audit(conn, "login_succeeded", subject_id=account["id"])
        return {"id": account["id"], "role": role, "roll_number": account["roll_number"],
                "name": account["name"], "csrf_token": csrf}, token


def current_session(token: str | None) -> dict | None:
    if not token or len(token) > 128:
        return None
    with engine().connect() as conn:
        row = conn.execute(sa.select(accounts.c.id, accounts.c.role, accounts.c.roll_number, accounts.c.name,
                                     sessions.c.csrf_token).join(sessions, accounts.c.id == sessions.c.account_id)
                           .where(sessions.c.token_hash == token_digest(token), sessions.c.expires_at > now()))
        match = row.mappings().first()
        return dict(match) if match else None


def main() -> None:
    command = sys.argv[1] if len(sys.argv) == 2 else ""
    if command == "init-key":
        init_key()
    elif command in ("create-admin", "reset-admin"):
        password = getpass.getpass("Admin password: ")
        if password != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords differ")
        (create_admin if command == "create-admin" else reset_admin)(password)
        print("Admin credentials saved")
    else:
        raise SystemExit("Usage: python -m cjudge.identity {init-key|create-admin|reset-admin}")


if __name__ == "__main__":
    main()
