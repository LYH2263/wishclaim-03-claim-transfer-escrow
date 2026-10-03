from datetime import datetime, timedelta, timezone
from app.modules.claim_transfer.projection import COUNTDOWN_PENDING_NOTE, project_card

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_claimed_card_has_countdown_and_policy():
    wish = {"id": 1, "status": "claimed", "claimer": "alice",
            "expires_at": (NOW + timedelta(seconds=90)).isoformat()}
    card = project_card(wish, NOW)
    assert card["claimer"] == "alice"
    assert card["remain_seconds"] == 90
    assert card["ttl_policy"] == "reset_full"
    assert card["pending_transfer"] is None
    assert card["transfer_note"] is None


def test_open_wish_has_no_countdown():
    card = project_card({"id": 2, "status": "open", "claimer": None, "expires_at": None}, NOW)
    assert card["remain_seconds"] is None


def test_card_pins_new_claimer_after_transfer():
    # 确认后的 wishes 行：投影必须钉新人，墙与详情同源
    wish = {"id": 1, "status": "claimed", "claimer": "bob",
            "claimed_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(seconds=86400)).isoformat()}
    card = project_card(wish, NOW)
    assert card["claimer"] == "bob"
    assert card["remain_seconds"] == 86400


def test_pending_offer_marker_and_note():
    wish = {"id": 1, "status": "claimed", "claimer": "alice",
            "expires_at": (NOW + timedelta(seconds=120)).isoformat()}
    pending = {"id": 7, "from_claimer": "alice", "target_claimer": "bob",
               "created_at": NOW.isoformat()}
    card = project_card(wish, NOW, pending)
    assert card["pending_transfer"]["target_claimer"] == "bob"
    assert card["transfer_note"] == COUNTDOWN_PENDING_NOTE
    # 托管期间倒计时仍按当前 expires_at 走，确认后才重开
    assert card["remain_seconds"] == 120


def test_countdown_floored_at_zero():
    wish = {"id": 1, "status": "claimed", "claimer": "alice",
            "expires_at": (NOW - timedelta(seconds=5)).isoformat()}
    assert project_card(wish, NOW)["remain_seconds"] == 0
