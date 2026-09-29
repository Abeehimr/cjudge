from datetime import datetime, timedelta, timezone
import pytest
from cjudge.labs import LabError, phase, setup_open, submission_allowed


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
