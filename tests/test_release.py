from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from cjudge import labs, identity


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


def test_release_visibility_and_archive_are_independent():
    from cjudge.labs.release import visible
    timestamp = datetime.now(timezone.utc)
    lab = dict(starts_at=timestamp - timedelta(hours=2), ends_at=timestamp,
        first_released_at=timestamp, reveal_results=False, archived_at=None)
    assert labs.phase(lab, timestamp) == 'Results released'
    with pytest.raises(labs.LabError): visible(lab)
    visible({**lab, 'reveal_results': True})
    archived = {**lab, 'archived_at': timestamp}
    assert labs.phase(archived, timestamp) == 'Archived'
    with pytest.raises(labs.LabError): labs.editable(archived)


def test_csv_neutralizes_untrusted_formula_cells():
    from cjudge.labs.exports import safe_cell
    for cell in ('=1+1', ' +SUM(A1)', '-1', '@cmd', '\troll', '\nname'):
        assert safe_cell(cell).startswith("'")
    assert safe_cell('Ada') == 'Ada'


def test_archive_verification_rejects_corrupt_content(tmp_path):
    import hashlib
    import zipfile
    from cjudge.labs.archive import verify
    path = tmp_path / 'test.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('data', b'wrong')
        archive.writestr('manifest.json', b'{}')
    manifest = {'entries': [{'path': 'data', 'size': 5, 'sha256': hashlib.sha256(b'right').hexdigest()}]}
    with pytest.raises(OSError): verify(path, manifest)


def test_private_notice_targets_only_recipient_and_admin_events():
    from unittest.mock import MagicMock
    from cjudge.judging import queue
    conn, lab_id, student_id, admin_id = MagicMock(), uuid4(), uuid4(), uuid4()
    with patch.object(identity, 'audit'), patch.object(queue, 'notify') as queued, patch.object(labs, 'notify') as public:
        labs.announce(conn, lab_id, 'Private reason', admin_id, student_id)
        queued.assert_called_once_with(conn, student_id)
        public.assert_not_called()
