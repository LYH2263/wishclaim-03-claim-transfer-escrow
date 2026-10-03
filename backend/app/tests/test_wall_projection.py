from datetime import datetime, timedelta, timezone
from app.engines.wall_projection import project_wish

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(minutes=5)).isoformat()

def _wish(claimer="alice", status="claimed", expires_at=EXP):
    return {"id": 1, "title": "键盘", "status": status,
            "claimer": claimer, "expires_at": expires_at}

def test_countdown_ticks_down_from_expiry():
    p = project_wish(_wish(), NOW)
    assert p["remaining_seconds"] == 300
    assert project_wish(_wish(), NOW + timedelta(minutes=4))["remaining_seconds"] == 60

def test_expired_countdown_floors_at_zero():
    p = project_wish(_wish(expires_at=(NOW - timedelta(seconds=1)).isoformat()), NOW)
    assert p["remaining_seconds"] == 0

def test_unclaimed_has_no_countdown():
    p = project_wish(_wish(status="open", claimer=None, expires_at=None), NOW)
    assert p["remaining_seconds"] is None and p["transfer"] is None

def test_pending_transfer_is_attached():
    order = {"id": 7, "wish_id": 1, "from_claimer": "alice", "to_claimer": "bob"}
    p = project_wish(_wish(), NOW, order)
    assert p["transfer"]["to_claimer"] == "bob" and p["transfer"]["id"] == 7

def test_projection_pins_new_claimer_after_confirm():
    # Confirmed transfer: wishes.claimer is bob while expires_at stays unchanged.
    p = project_wish(_wish(claimer="bob"), NOW)
    assert p["claimer"] == "bob" and p["remaining_seconds"] == 300
    assert p["transfer"] is None
