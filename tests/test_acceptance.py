import http.client
import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch

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
