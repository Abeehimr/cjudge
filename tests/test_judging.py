import threading
from unittest.mock import MagicMock, patch

import pytest

from cjudge import runner
from cjudge.judging.worker import judge, pool_size, validate_capacity


def test_judging_checks_all_full_outputs_and_keeps_exact_score():
    connection = MagicMock()
    connection.execute.return_value.mappings.return_value.one.return_value = {
        'config': {'title': 'Gate', 'maximum_marks': '7'}, 'cases_key': 'key', 'case_count': 2}
    compiled = runner.Result('OK', b'', b'', 0, 0, 0, b'binary')
    tail = b'x' * 65536 + b'wrong'
    results = [runner.Result('OK', b'yes', b'', 0, 0, 0),
               runner.Result('OK', tail, b'', 0, 0, 0, stdout_truncated=True)]
    with patch('cjudge.identity.engine') as engine, patch('cjudge.tasks.load_cases', return_value=[(b'', b'yes'), (b'', tail[:-5] + b'right')]), \
            patch('cjudge.submissions.files.read', return_value=b'source'), patch('cjudge.runner.compile_c', return_value=compiled), \
            patch('cjudge.runner.execute', side_effect=results) as execute:
        engine.return_value.connect.return_value.__enter__.return_value = connection
        result = judge({'revision_id': 'revision'}, threading.Event())
        assert execute.call_count == 2
        assert result['passed'] == 1 and result['verdict'] == 'Failed'
        assert (result['score_numerator'], result['score_denominator']) == ('7', '2')
        assert result['cases'][1]['verdict'] == 'WA'
        assert len(result['cases'][1]['stdout']) == 65536
        assert result['cases'][1]['stdout_truncated']


def test_pool_configuration(monkeypatch):
    monkeypatch.setenv('CJUDGE_SANDBOX_INSTANCES', '2')
    assert pool_size() == 2
    with patch('pathlib.Path.read_text', return_value=str(1024**3)):
        with pytest.raises(ValueError, match='768 MiB'):
            validate_capacity(2)
        validate_capacity(1)
    for value in ['0', '33', 'bad']:
        monkeypatch.setenv('CJUDGE_SANDBOX_INSTANCES', value)
        with pytest.raises(ValueError):
            pool_size()
