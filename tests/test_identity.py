import os

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from cjudge import identity
from cjudge.identity.api import same_origin


def test_write_origin_matches_allowed_request_address(monkeypatch) -> None:
    monkeypatch.setenv('CJUDGE_ALLOWED_HOSTS', 'localhost,127.0.0.1,192.0.2.10,192.0.2.11')

    def request(host: str, origin: str | None) -> Request:
        headers = [(b'host', host.encode())]
        if origin is not None:
            headers.append((b'origin', origin.encode()))
        return Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': headers})

    for host in ('localhost', '127.0.0.1', '192.0.2.10', '192.0.2.11'):
        same_origin(request(host, f'https://{host}:8443'))
        same_origin(request(f'{host}:8443', f'https://{host}:8443'))
    same_origin(request('LOCALHOST:8443', 'https://localhost:8443'))
    for host, origin in (
        ('192.0.2.10', 'https://192.0.2.11:8443'),
        ('192.0.2.10', 'http://192.0.2.10:8443'),
        ('192.0.2.10', 'https://192.0.2.10:8080'),
        ('192.0.2.10:9999', 'https://192.0.2.10:9999'),
        ('evil.example', 'https://evil.example:8443'),
        ('localhost', None),
    ):
        with pytest.raises(HTTPException) as error:
            same_origin(request(host, origin))
        assert error.value.status_code == 403


def test_global_rolls_and_csv_validation() -> None:
    assert identity.normalize_roll(" 001ab/2 ") == "001AB/2"
    assert identity.parse_csv(b"\xef\xbb\xbfroll_number,name\r\n001a,Ada\r\n2,Grace\r\n") == [
        ("001A", "Ada"), ("2", "Grace")]
    for payload in (
        b"roll_number,name\nA,Ada\na,Grace\n", b"name,roll_number\nAda,A\n",
        b"roll_number,name\nA,\n", b"roll_number,name\nA,Ada,extra\n",
        b"roll_number,name\nA,Ada\nA,Grace\n", b"\xff",
    ):
        with pytest.raises(ValueError):
            identity.parse_csv(payload)
    with pytest.raises(ValueError, match="reserved"):
        identity.normalize_roll(" admin ")
    with pytest.raises(ValueError, match="reserved"):
        identity.parse_csv(b"roll_number,name\nAdMiN,Student\n")
    with pytest.raises(ValueError):
        identity.normalize_name("bad\nname")
    with pytest.raises(ValueError):
        identity.parse_csv(b"roll_number,name\nA,Ada\n" * 200000)


def test_password_storage_and_key_survival(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(identity, "KEY_FILE", tmp_path / "credentials.key")
    with pytest.raises(RuntimeError):
        identity.cipher()
    identity.init_key()
    assert os.stat(identity.KEY_FILE).st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        identity.init_key()
    password = identity.generate_password()
    assert len(password) == 6 and all(char in identity.PASSWORD_ALPHABET for char in password)
    hashed = identity.hash_password(password)
    assert identity.verify_password(hashed, password)
    assert not identity.verify_password(hashed, "wrong")
    encrypted = identity.cipher().encrypt(password.encode())
    assert password.encode() not in encrypted
    assert identity.cipher().decrypt(encrypted).decode() == password
    assert identity.token_digest("abc") != identity.token_digest("abd")
