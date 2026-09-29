from datetime import datetime, timedelta, timezone
import pytest
from cjudge.labs import LabError, phase, setup_open, submission_allowed
from cjudge.lab_binding import client_ip
from starlette.requests import Request


def test_time_boundaries_and_freeze():
    start = datetime(2026, 9, 30, tzinfo=timezone.utc)
    lab = {'starts_at': start, 'ends_at': start + timedelta(hours=2)}
    assert phase({'starts_at': None}, start) == 'Draft'
    assert phase(lab, start - timedelta(microseconds=1)) == 'Scheduled'
    assert phase(lab, start) == 'Running'
    assert phase(lab, lab['ends_at']) == 'Ended'
    with pytest.raises(LabError):
        setup_open(lab, start)
    submission_allowed(lab, {'frozen': False}, start)
    with pytest.raises(LabError) as exc:
        submission_allowed(lab, {'frozen': True}, start)
    assert exc.value.status == 423
    with pytest.raises(LabError):
        submission_allowed(lab, {'frozen': False}, lab['ends_at'])


def test_forwarded_ip_is_trusted_only_from_proxy(monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo', lambda *args, **kwargs: [(None, None, None, None, ('172.18.0.2', 0))])
    def request(peer, header):
        return Request({'type': 'http', 'client': (peer, 1234), 'headers': [(b'x-real-ip', header.encode())]})
    assert client_ip(request('192.0.2.1', '198.51.100.1')) == '192.0.2.1'
    assert client_ip(request('172.18.0.2', '198.51.100.1')) == '198.51.100.1'
    with pytest.raises(LabError) as exc:
        client_ip(request('172.18.0.2', 'invalid'))
    assert exc.value.status == 400
