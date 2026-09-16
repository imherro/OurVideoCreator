from backend.app import _event_cursor


def test_new_event_stream_starts_at_latest_event():
    assert _event_cursor(17_760) == 17_760


def test_recent_reconnect_replays_missed_events():
    details={'oldest_retained':17_000,'requested_retained':True,'visible_backlog':10}
    assert _event_cursor(17_760, last_event_id="17750", **details) == 17_750
    assert _event_cursor(17_760, after=17_755, **{**details,'visible_backlog':5}) == 17_755


def test_stale_reconnect_skips_unbounded_history():
    over_limit={'oldest_retained':100,'requested_retained':True,'visible_backlog':501}
    outside={'oldest_retained':10_000,'requested_retained':False,'visible_backlog':20}
    assert _event_cursor(17_760, last_event_id="100", **over_limit) == 17_760
    assert _event_cursor(17_760, after=0, **outside) == 17_760


def test_identity_gap_uses_visible_backlog_not_numeric_distance():
    assert _event_cursor(
        502,last_event_id=1,oldest_retained=1,requested_retained=True,visible_backlog=1,
    ) == 1
