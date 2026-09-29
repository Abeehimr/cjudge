from uuid import UUID

from cjudge import tasks


def test_private_immutable_case_sets(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, 'ARTIFACTS', tmp_path)
    original = [(b'1 2\n', b'3\n')]
    first = tasks.save_cases(original)
    second = tasks.save_cases([(b'2 3\n', b'5\n')])
    assert isinstance(first, UUID) and first != second
    assert tasks.load_cases(first) == original
    assert tasks.load_cases(second) == [(b'2 3\n', b'5\n')]
    assert (tmp_path / f'{first}.zip').stat().st_mode & 0o777 == 0o400
    assert tasks.load_cases(None) == []
