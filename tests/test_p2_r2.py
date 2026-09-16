from __future__ import annotations

import asyncio
import json

from backend import database
from backend import store as s
from backend.app import events


class StreamRequest:
    def __init__(self, last_event_id=None):
        self.headers = {}
        if last_event_id is not None:
            self.headers['last-event-id'] = str(last_event_id)

    async def is_disconnected(self):
        return False


async def first_stream_chunk(*, after=None, last_event_id=None):
    response = await events(StreamRequest(last_event_id), after=after)
    iterator = response.body_iterator
    try:
        return await asyncio.wait_for(anext(iterator), timeout=3)
    finally:
        await iterator.aclose()


def stream_id(chunk):
    for line in chunk.splitlines():
        if line.startswith('id: '):
            return int(line.removeprefix('id: '))
    return None


def retained_ids():
    with s.db() as connection:
        return [row['id'] for row in connection.execute('SELECT id FROM events ORDER BY id')]


def test_p2_r2_large_rollback_gap_replays_through_last_event_id_and_after():
    with s.db() as connection:
        connection.execute('DELETE FROM events')
    s.event('gap-project', {'type':'project','revision':1})
    first_id = retained_ids()[0]

    rolled_back = database.connect()
    try:
        for revision in range(2, 502):
            s._event(rolled_back, 'gap-project', {'type':'project','revision':revision})
        rolled_back.rollback()
    finally:
        rolled_back.close()

    s.event('gap-project', {'type':'project','revision':502})
    visible = retained_ids()
    assert len(visible) == 2
    assert visible[0] == first_id
    assert visible[1] - visible[0] == 501

    last_event_chunk = asyncio.run(first_stream_chunk(last_event_id=first_id))
    after_chunk = asyncio.run(first_stream_chunk(after=first_id))
    received = [stream_id(last_event_chunk), stream_id(after_chunk)]
    print(json.dumps({
        'case':'large_rollback_gap_stream',
        'database':s.init()['database_name'],
        'rollback_event_count':500,
        'retained_ids':visible,
        'actual_backlog_rows':1,
        'requested_cursor':first_id,
        'received_ids':received,
    },sort_keys=True))
    assert received == [visible[1], visible[1]]


def test_p2_r2_stream_policy_uses_visible_rows_for_initial_small_overlimit_and_expired(monkeypatch):
    with s.db() as connection:
        connection.execute('DELETE FROM events')
    s.event('policy-project',{'type':'project','revision':1})
    first = retained_ids()[0]
    s.event('policy-project',{'type':'project','revision':2})
    second = retained_ids()[-1]

    initial = asyncio.run(first_stream_chunk())
    no_gap = asyncio.run(first_stream_chunk(last_event_id=first))
    assert stream_id(initial) is None
    assert stream_id(no_gap) == second

    rolled_back = database.connect()
    try:
        s._event(rolled_back,'policy-project',{'type':'project','revision':3})
        rolled_back.rollback()
    finally:
        rolled_back.close()
    s.event('policy-project',{'type':'project','revision':4})
    small_gap_latest = retained_ids()[-1]
    small_gap = asyncio.run(first_stream_chunk(after=second))
    assert stream_id(small_gap) == small_gap_latest

    with s.db() as connection:
        connection.execute('DELETE FROM events')
        for revision in range(502):
            s._event(connection,'overlimit-project',{'type':'project','revision':revision})
    overlimit_ids = retained_ids()
    overlimit = asyncio.run(first_stream_chunk(last_event_id=overlimit_ids[0]))
    assert stream_id(overlimit) is None

    monkeypatch.setattr(s,'EVENT_RETENTION',3)
    with s.db() as connection:
        connection.execute('DELETE FROM events')
    expired_cursor = None
    for revision in range(4):
        s.event('expired-project',{'type':'project','revision':revision})
        if revision == 0:
            expired_cursor = retained_ids()[0]
    expired_ids = retained_ids()
    assert expired_cursor not in expired_ids and len(expired_ids) == 3
    expired = asyncio.run(first_stream_chunk(last_event_id=expired_cursor))
    assert stream_id(expired) is None

    print(json.dumps({
        'case':'stream_cursor_policy',
        'initial_connection':'head_only',
        'no_gap_received':second,
        'small_gap_received':small_gap_latest,
        'overlimit_visible_backlog':501,
        'overlimit_result':'head_only',
        'expired_cursor':expired_cursor,
        'expired_retained_ids':expired_ids,
        'expired_result':'head_only',
    },sort_keys=True))
