import http.client
import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest


def test_idle_connection_retry_requires_safe_request() -> None:
    with patch('ssl.create_default_context'):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/acceptance.py'))
    client_class = namespace['Client']
    response = MagicMock(status=200)
    response.read.return_value = b'{}'
    for method, headers, retry in [('GET', {}, True), ('POST', {'Idempotency-Key': 'same-key'}, True), ('POST', {}, False)]:
        stale, fresh = MagicMock(), MagicMock()
        stale.getresponse.side_effect = http.client.RemoteDisconnected()
        fresh.getresponse.return_value = response
        with patch.dict(client_class.call.__globals__, Connection=MagicMock(side_effect=[stale, fresh])):
            client = client_class()
            if retry:
                assert client.call('/test', method, b'body', headers)[0] == {}
                assert stale.request.call_args == fresh.request.call_args
            else:
                with pytest.raises(http.client.RemoteDisconnected):
                    client.call('/test', method, b'body', headers)
                fresh.request.assert_not_called()
            stale.close.assert_called_once()


def test_performance_summary_uses_nearest_rank_and_memory_units() -> None:
    with patch('ssl.create_default_context'):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/acceptance.py'))
    assert namespace['metrics'](list(range(1, 101))) == {
        'requests': 100, 'p50_ms': 50, 'p95_ms': 95, 'p99_ms': 99}
    assert namespace['memory_bytes']('1.5GiB') == 1610612736


def test_resource_sampler_records_database_waits_without_query_text() -> None:
    with patch('ssl.create_default_context'):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/acceptance.py'))
    stop, peaks = MagicMock(), {}
    stop.is_set.side_effect = [False, True]
    results = [SimpleNamespace(returncode=0, stdout='test-api-1|125.0%|1MiB / 1GiB\n'),
        SimpleNamespace(returncode=0, stdout='[{"state":"active","event":"Lock:transactionid",'
            '"connections":2,"blocked":1,"query_age_ms":1200}]')]
    with patch('subprocess.run', side_effect=results):
        namespace['sample_resources']('test', stop, peaks)
    assert peaks['api'] == {'cpu_percent': 125, 'memory_bytes': 1048576}
    assert peaks['database_activity']['active/Lock:transactionid']['blocked_samples'] == 1
