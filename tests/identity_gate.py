"""Run with: docker compose run --rm -v ./tests:/app/tests:ro api python tests/identity_gate.py"""

import json
import secrets
import threading
import tempfile
from datetime import timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import sqlalchemy as sa

from cjudge import identity as store


BASE = "http://api:8000/api"
ORIGIN = "https://localhost:8443"


def call(path, method="GET", body=None, cookie=None, csrf=None, content_type="application/json", origin=ORIGIN):
    data = json.dumps(body).encode() if content_type == "application/json" and body is not None else body
    headers = {"Origin": origin, "Host": "localhost"}
    if data is not None:
        headers["Content-Type"] = content_type
    if cookie:
        headers["Cookie"] = f"cjudge_session={cookie}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        response = urlopen(request, timeout=10)
    except HTTPError as error:
        return error.code, None, None
    payload = response.read()
    result = json.loads(payload) if payload else None
    set_cookie = response.headers.get("Set-Cookie", "")
    return response.status, result, set_cookie


def login(role, identifier, password):
    status, account, header = call(f"/auth/{role}/login", "POST", {"identifier": identifier, "password": password})
    return status, account, header.split(";", 1)[0].split("=", 1)[1] if status == 200 else None, header


def main():
    suffix = secrets.token_hex(4).upper()
    roll = f"TEST{suffix}"
    other_roll = f"TEST{suffix}B"
    admin_created = False
    test_ids = []
    attempt_keys = [f"student:{roll}", f"student:{other_roll}", f"student:TESTUNKNOWN{suffix}", "admin:ADMIN"]
    assert call("/auth/session")[0] == 401
    with store.engine().connect() as conn:
        admin_id = conn.execute(sa.select(store.accounts.c.id).where(store.accounts.c.role == "admin")).scalar_one_or_none()
    if admin_id is None:
        admin_password = "AdminTest-" + secrets.token_urlsafe(18)
        store.create_admin(admin_password)
        admin_created = True
        assert login("admin", "admin", "wrong")[0] == 401
        status, admin, admin_cookie, header = login("admin", "admin", admin_password)
        assert status == 200 and "HttpOnly" in header and "Secure" in header and "SameSite=lax" in header
        admin_id = admin["id"]
        admin_csrf = admin["csrf_token"]
    else:
        admin_cookie, admin_csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
        with store.engine().begin() as conn:
            conn.execute(sa.insert(store.sessions).values(token_hash=store.token_digest(admin_cookie),
                account_id=admin_id, csrf_token=admin_csrf, expires_at=store.now() + timedelta(hours=8)))
    try:
        assert call("/admin/students", cookie=admin_cookie)[0] == 200
        assert call("/admin/students", "POST", {"roll_number": " admin ", "name": "Reserved"},
                    admin_cookie, admin_csrf)[0] == 400
        assert call("/admin/students/import", "POST", b"roll_number,name\nADMIN,Reserved\n",
                    admin_cookie, admin_csrf, "text/csv")[0] == 400
        assert call("/admin/students", method="POST", body={"roll_number": roll, "name": "Ada"},
                    cookie=admin_cookie)[0] == 403
        assert call("/admin/students", method="POST", body={"roll_number": roll, "name": "Ada"},
                    cookie=admin_cookie, csrf=admin_csrf, origin="https://evil.example")[0] == 403
        status, student, _ = call("/admin/students", method="POST", body={"roll_number": roll, "name": "Ada"},
                                  cookie=admin_cookie, csrf=admin_csrf)
        assert status == 201, status
        test_ids.append(student["id"])
        assert student["roll_number"] == roll
        assert call("/admin/students", method="POST", body={"roll_number": roll, "name": "Ada"},
                    cookie=admin_cookie, csrf=admin_csrf)[0] == 409
        status, sheet, _ = call("/admin/students/credentials", "POST", {"ids": [student["id"]]},
                                admin_cookie, admin_csrf)
        assert status == 200 and len(sheet) == 1
        password = sheet[0]["password"]
        with store.engine().connect() as conn:
            record = conn.execute(sa.select(store.accounts.c.password_hash, store.accounts.c.encrypted_password)
                                  .where(store.accounts.c.id == student["id"])).one()
            assert password not in record.password_hash and password.encode() not in record.encrypted_password
            with tempfile.NamedTemporaryFile() as wrong_key:
                wrong_key.write(store.Fernet.generate_key())
                wrong_key.flush()
                original_key = store.KEY_FILE
                try:
                    store.KEY_FILE = store.Path(wrong_key.name)
                    try:
                        store.checked_cipher(conn)
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("Wrong credential key accepted")
                finally:
                    store.KEY_FILE = original_key
        assert login("student", roll, "wrong")[0] == 401
        status, student_session, student_cookie, _ = login("student", roll.lower(), password)
        assert status == 200 and student_session["role"] == "student"
        assert call("/admin/students", cookie=student_cookie)[0] == 403
        assert call("/admin/students", "POST", {"roll_number": other_roll, "name": "Grace"},
                    student_cookie, student_session["csrf_token"])[0] == 403
        assert call("/auth/session", cookie=student_cookie)[0] == 200
        csv = f"roll_number,name\n{roll},Different\n{other_roll},Grace\n".encode()
        status, report, _ = call("/admin/students/import", "POST", csv, admin_cookie, admin_csrf, "text/csv")
        assert status == 200 and report == {"created": [other_roll], "existing": [roll], "name_mismatches": [roll]}
        with store.engine().connect() as conn:
            test_ids.append(str(conn.execute(sa.select(store.accounts.c.id)
                                             .where(store.accounts.c.roll_number == other_roll)).scalar_one()))
        assert call("/admin/students/import", "POST",
                    f"roll_number,name\nBAD{suffix},X\nbad{suffix},Y\n".encode(),
                    admin_cookie, admin_csrf, "text/csv")[0] == 400
        with store.engine().connect() as conn:
            assert conn.execute(sa.select(sa.func.count()).select_from(store.accounts)
                                .where(store.accounts.c.roll_number == f"BAD{suffix}")).scalar_one() == 0
        concurrent_roll = f"TEST{suffix}C"
        outcomes = []
        workers = [threading.Thread(target=lambda: outcomes.append(
            store.import_students([(concurrent_roll, "Concurrent")], admin_id))) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        with store.engine().connect() as conn:
            test_ids.append(str(conn.execute(sa.select(store.accounts.c.id)
                                             .where(store.accounts.c.roll_number == concurrent_roll)).scalar_one()))
        assert sorted(len(result["created"]) for result in outcomes) == [0, 1], [
            (len(result["created"]), len(result["existing"])) for result in outcomes]
        assert call(f"/admin/students/{student['id']}", "PATCH", {"name": "Ada Updated"},
                    admin_cookie, admin_csrf)[1]["name"] == "Ada Updated"
        second_id = test_ids[-2]
        status, old_sheet, _ = call("/admin/students/credentials", "POST", {"ids": [student["id"], second_id]},
                                     admin_cookie, admin_csrf)
        assert status == 200
        old_passwords = {entry["id"]: entry["password"] for entry in old_sheet}
        assert call("/admin/students/reset", "POST", {"ids": [student["id"], str(uuid4())]},
                    admin_cookie, admin_csrf)[0] == 404
        assert call("/auth/session", cookie=student_cookie)[0] == 200
        assert call("/admin/students/reset", "POST", {"ids": [student["id"], student["id"]]},
                    admin_cookie, admin_csrf)[0] == 400
        assert call("/admin/students/reset", "POST", {"ids": [student["id"]]},
                    student_cookie, student_session["csrf_token"])[0] == 403
        assert call("/admin/students/reset", "POST", {"ids": [student["id"]]},
                    admin_cookie)[0] == 403
        status, new_sheet, _ = call("/admin/students/reset", "POST", {"ids": [student["id"], second_id]},
                                    admin_cookie, admin_csrf)
        assert status == 200 and [entry["id"] for entry in new_sheet] == [student["id"], second_id]
        assert all(len(entry["password"]) == 6 and entry["password"].isalnum()
                   and entry["password"] == entry["password"].lower() for entry in new_sheet)
        assert call("/auth/session", cookie=student_cookie)[0] == 401
        assert all(login("student", entry["roll_number"], old_passwords[entry["id"]])[0] == 401
                   for entry in new_sheet)
        assert all(login("student", entry["roll_number"], entry["password"])[0] == 200
                   for entry in new_sheet)
        password = new_sheet[0]["password"]
        status, new_credential, _ = call(f"/admin/students/{student['id']}/reset", "POST", None,
                    admin_cookie, admin_csrf)
        assert status == 200 and new_credential["password"] != password
        assert call("/auth/session", cookie=student_cookie)[0] == 401
        assert login("student", roll, password)[0] == 401
        status, new_student, new_cookie, _ = login("student", roll, new_credential["password"])
        assert status == 200
        with store.engine().begin() as conn:
            conn.execute(sa.update(store.sessions).where(store.sessions.c.token_hash == store.token_digest(new_cookie))
                         .values(expires_at=store.now()))
        assert call("/auth/session", cookie=new_cookie)[0] == 401
        status, student_session, student_cookie, _ = login("student", roll, new_credential["password"])
        assert status == 200
        assert call("/auth/logout", "POST", None, student_cookie, student_session["csrf_token"])[0] == 204
        assert call("/auth/session", cookie=student_cookie)[0] == 401
        unknown = f"TESTUNKNOWN{suffix}"
        for _ in range(6):
            assert login("student", unknown, "bad")[0] == 401
        with store.engine().connect() as conn:
            assert conn.execute(sa.select(sa.func.count()).select_from(store.audit_events)
                                .where(store.audit_events.c.action == "login_throttled",
                                       store.audit_events.c.detail["identifier"].as_string() == f"student:{unknown}")).scalar_one() >= 1
        if admin_created:
            replacement = "AdminReplacement-" + secrets.token_urlsafe(16)
            store.reset_admin(replacement)
            assert call("/auth/session", cookie=admin_cookie)[0] == 401
            assert login("admin", "admin", admin_password)[0] == 401
            assert login("admin", "admin", replacement)[0] == 200
        print("PASS: migration, admin/student login, roles, CSRF, CSV, credentials, reset, expiry, logout, throttle")
    finally:
        with store.engine().begin() as conn:
            ids = [admin_id, *test_ids] if admin_created else test_ids
            conn.execute(sa.delete(store.sessions).where(store.sessions.c.account_id.in_(ids)))
            conn.execute(sa.delete(store.audit_events).where(sa.or_(store.audit_events.c.actor_id.in_(ids),
                                                                    store.audit_events.c.subject_id.in_(ids))))
            conn.execute(sa.delete(store.audit_events).where(
                store.audit_events.c.detail["identifier"].as_string() == f"student:TESTUNKNOWN{suffix}"))
            conn.execute(sa.delete(store.accounts).where(store.accounts.c.id.in_(ids)))
            conn.execute(sa.delete(store.login_attempts).where(store.login_attempts.c.identifier.in_(attempt_keys)))


if __name__ == "__main__":
    main()
