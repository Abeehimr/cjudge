import asyncio
from unittest.mock import patch, MagicMock

import httpx
import pytest
from fastapi import HTTPException

from cjudge.api import app


def test_health_and_private_docs() -> None:
    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            assert (await client.get("/api/health")).json() == {"status": "ok"}
            assert (await client.get("/docs")).status_code == 404
            assert (await client.get("/openapi.json")).status_code == 404
            assert (await client.get("/api/health", headers={"host": "evil.example"})).status_code == 400

    asyncio.run(check())


def test_ready_without_database_configuration() -> None:
    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            assert (await client.get("/api/ready")).status_code == 503

    with patch.dict("os.environ", {}, clear=True):
        asyncio.run(check())


def test_transaction_diagnostics_omit_private_error_contents(caplog) -> None:
    from cjudge.submissions.api import transaction
    with patch('cjudge.identity.engine', return_value=MagicMock()):
        with pytest.raises(HTTPException) as error:
            with transaction():
                raise OSError('private source and credentials')
    assert error.value.status_code == 503
    assert 'Transaction unavailable (OSError)' in caplog.text
    assert 'private source and credentials' not in caplog.text
