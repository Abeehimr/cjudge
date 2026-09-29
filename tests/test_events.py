import asyncio
from uuid import uuid4
from cjudge.events import EventHub


def test_notifications_coalesce_and_isolate_labs():
    async def check():
        hub = EventHub()
        hub.available = True
        a, b, student = uuid4(), uuid4(), uuid4()
        async with hub.subscribe(a, student) as queue_a, hub.subscribe(b, student) as queue_b:
            hub.refresh(lab_id=str(a))
            hub.refresh(lab_id=str(a))
            assert queue_a.qsize() == 1 and queue_b.empty()
            queue_a.get_nowait()
            hub.refresh(account_id=str(student))
            assert queue_a.qsize() == queue_b.qsize() == 1
        assert not hub.clients
    asyncio.run(check())
