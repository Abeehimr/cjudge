from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from cjudge import labs


def test_stop_uses_server_time_and_preserves_accepted_work():
    timestamp = datetime.now(timezone.utc)
    lab = dict(id=uuid4(), starts_at=timestamp - timedelta(minutes=1), ends_at=timestamp + timedelta(hours=1), first_released_at=None)
    with patch.object(labs, 'now', return_value=timestamp), patch.object(labs.identity, 'audit'), patch.object(labs, 'changed', return_value=lab) as changed:
        labs.stop(None, lab, 'Class finished', uuid4())
        assert changed.call_args.kwargs['ends_at'] == timestamp
        for invalid in ({**lab, 'ends_at': timestamp}, {**lab, 'first_released_at': timestamp}):
            with pytest.raises(labs.LabError): labs.stop(None, invalid, 'Finished', uuid4())
        with pytest.raises(labs.LabError): labs.stop(None, lab, ' ', uuid4())
    with pytest.raises(labs.LabError):
        labs.submission_allowed({**lab, 'ends_at': timestamp}, {'frozen': False}, timestamp)
