"""One PostgreSQL listener per API process; SSE queues contain only invalidations."""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from uuid import UUID

import psycopg
import sqlalchemy as sa


def publish(conn: sa.Connection, *, lab_id: UUID | None = None, account_id: UUID | None = None) -> None:
    conn.execute(sa.select(sa.func.pg_notify('cjudge_events', json.dumps({
        'lab_id': str(lab_id) if lab_id else None, 'account_id': str(account_id) if account_id else None}))))


class EventHub:
    def __init__(self) -> None:
        self.clients: dict[asyncio.Queue, tuple[str, str]] = {}
        self.available = False

    def refresh(self, lab_id: str | None = None, account_id: str | None = None) -> None:
        for queue, (lab, account) in list(self.clients.items()):
            if lab_id is None and account_id is None or lab_id == lab or account_id == account:
                if not queue.full():
                    queue.put_nowait(True)

    @asynccontextmanager
    async def subscribe(self, lab_id: UUID, account_id: UUID):
        if not self.available:
            raise RuntimeError('Live connection unavailable; reconnect shortly')
        if len(self.clients) >= 512 or sum(account == str(account_id) for _, account in self.clients.values()) >= 5:
            raise RuntimeError('Too many live connections; close another lab tab')
        # Invalidations coalesce: a slow client needs one authoritative refresh.
        queue = asyncio.Queue(maxsize=1)
        self.clients[queue] = str(lab_id), str(account_id)
        try:
            yield queue
        finally:
            self.clients.pop(queue, None)

    async def listen(self) -> None:
        delay = 1
        url = sa.make_url(os.environ['DATABASE_URL']).set(drivername='postgresql').render_as_string(hide_password=False)
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
                    await conn.execute('LISTEN cjudge_events')
                    self.available = True
                    self.refresh()  # Reconcile updates missed during a listener outage.
                    delay = 1
                    async for note in conn.notifies():
                        try:
                            payload = json.loads(note.payload)
                        except ValueError:
                            continue
                        if not isinstance(payload, dict):
                            continue
                        self.refresh(payload.get('lab_id'), payload.get('account_id'))
            except (psycopg.Error, OSError):
                logging.getLogger(__name__).warning('Lab event listener disconnected; retrying')
                self.available = False
                self.refresh()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
            finally:
                self.available = False


hub = EventHub()


@asynccontextmanager
async def lifespan(app):
    listener = asyncio.create_task(hub.listen()) if os.getenv('DATABASE_URL') else None
    try:
        yield
    finally:
        if listener:
            listener.cancel()
            try:
                await listener
            except asyncio.CancelledError:
                pass
