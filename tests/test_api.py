import asyncio
from unittest.mock import patch

import httpx

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
