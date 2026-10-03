from datetime import datetime, timedelta, timezone
from app.engines.transfer_lock import confirm_plan, normalize_target, transfer_preview

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()

def test_preview_lists_target_and_current_expiry():
    r = transfer_preview("claimed", "alice", EXP, "bob")
    assert r["ok"] is True
    pv = r["preview"]
    assert pv["from_claimer"] == "alice"
    assert pv["to_claimer"] == "bob"
    assert pv["expires_at"] == EXP            # current expires_at, pinned for preview
    assert pv["ttl_policy"] == "inherit_remaining"

def test_preview_trims_target():
    assert transfer_preview("claimed", "alice", EXP, " bob ")["preview"]["to_claimer"] == "bob"

def test_preview_fails_when_not_claimed():
    for st in ("open", "released", "fulfilled"):
        assert transfer_preview(st, None, None, "bob")["ok"] is False
    assert transfer_preview("claimed", "alice", EXP, "bob")["ok"] is True

def test_preview_rejects_illegal_target():
    for bad in (None, "", "   "):
        r = transfer_preview("claimed", "alice", EXP, bad)
        assert r["ok"] is False and r["reason"] == "bad_target"
    assert normalize_target("  ") is None

def test_preview_rejects_self_transfer():
    r = transfer_preview("claimed", "alice", EXP, "alice")
    assert r["ok"] is False and r["reason"] == "target_is_self"

def test_confirm_swaps_only_claimer_and_inherits_ttl():
    p = confirm_plan("claimed", "alice", EXP, "alice", "bob", NOW)
    assert p["ok"] is True
    assert p["patch"]["claimer"] == "bob"
    # No expires_at in patch: remaining seconds are inherited, never refreshed.
    assert "expires_at" not in p["patch"]

def test_confirm_fails_when_wish_not_claimed():
    r = confirm_plan("open", None, None, "alice", "bob", NOW)
    assert r["ok"] is False and r["reason"] == "not_claimed"

def test_confirm_fails_when_claimer_moved():
    # TTL reclaim handed the row to someone else before confirm.
    r = confirm_plan("claimed", "carol", EXP, "alice", "bob", NOW)
    assert r["ok"] is False and r["reason"] == "claimer_changed"

def test_confirm_fails_when_ttl_expired():
    r = confirm_plan("claimed", "alice", (NOW - timedelta(seconds=1)).isoformat(),
                     "alice", "bob", NOW)
    assert r["ok"] is False and r["reason"] == "ttl_expired"

def test_confirm_fails_on_illegal_target():
    r = confirm_plan("claimed", "alice", EXP, "alice", "  ", NOW)
    assert r["ok"] is False and r["reason"] == "bad_target"
