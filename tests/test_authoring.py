"""Bounded authoring contracts; teacher programs are never run on the host."""
from dataclasses import replace
import pytest
from pydantic import ValidationError

from cjudge import runner
from cjudge.tasks.authoring import GenerationConfig, check_python, generate_case, AuthoringError
from cjudge.tasks.grading import Checker, compare_output


def test_authoring_contracts(monkeypatch):
    for config in ({'source': 'x'}, {'kind': 'python'}, {'kind': 'python', 'source': 'é' * 40000},
                   {'kind': 'python', 'source': 'accept()', 'ignore_case': True}):
        with pytest.raises(ValidationError):
            Checker(**config)
    checker = Checker(kind='python', source='accept()')
    with pytest.raises(ValueError):
        compare_output(b'', b'', checker)
    for changes in ({'seed': 2**63 - 1, 'count': 2}, {'count': 101}, {'seed': True}, {'generator': 'é' * 40000}):
        with pytest.raises(ValidationError):
            GenerationConfig(**(dict(generator='print(1)', reference='int main(){}') | changes))
    result = runner.Result('OK', b'AC\n', b'', 0, 0, 0)
    def sandbox(script, profile, files=None, **kwargs):
        assert profile == runner.Profile.CHECKER
        assert files['output'] == b'x' * (10 * 1024 * 1024)
        assert files['input'] == b'\x00\xff'
        return result
    monkeypatch.setattr(runner, 'run_python', sandbox)
    assert check_python(checker.source, b'\x00\xff', b'x' * (10 * 1024 * 1024), b'answer')
    for malformed in (b'', b'AC', b'AC\nWA\n', b'debug\nAC\n'):
        result = replace(result, stdout=malformed)
        with pytest.raises(runner.SandboxError):
            check_python(checker.source, b'\x00\xff', b'x' * (10 * 1024 * 1024), b'answer')
    config = GenerationConfig(generator='print(1)', reference='int main(){}')
    monkeypatch.setattr(runner, 'run_python', lambda *a, **kw: replace(result, verdict='TLE'))
    with pytest.raises(AuthoringError):
        generate_case(config, 0, b'fake')


def test_atomic_protected_artifacts(tmp_path, monkeypatch):
    from uuid import uuid4
    from cjudge import authoring
    monkeypatch.setenv('CJUDGE_AUTHORING_FILES', str(tmp_path))
    job, key = uuid4(), uuid4()
    authoring.save(job, key, 'in', b'\x00\xff')
    assert authoring.read(job, key, 'in') == b'\x00\xff'
    with pytest.raises(FileExistsError):
        authoring.save(job, key, 'in', b'overwrite')
    assert authoring.read(job, key, 'in') == b'\x00\xff'
    authoring.artifact_path(job, key, 'out').symlink_to('/etc/passwd')
    with pytest.raises(OSError):
        authoring.read(job, key, 'out')
    assert not list(tmp_path.rglob('*.tmp'))
