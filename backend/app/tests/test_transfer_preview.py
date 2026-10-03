from datetime import datetime, timedelta, timezone
from app.modules.claim_transfer.preview import TTL_POLICY, build_preview, valid_target

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=2)).isoformat()


def claimed_wish(**over):
    w = {"id": 1, "title": "键盘", "status": "claimed", "claimer": "alice",
         "claimed_at": (NOW - timedelta(hours=1)).isoformat(), "expires_at": EXP}
    w.update(over)
    return w


def test_policy_pinned_reset_full():
    assert TTL_POLICY == "reset_full"


def test_preview_lists_target_and_current_expiry_without_writing_wishes():
    w = claimed_wish()
    snapshot = dict(w)
    p = build_preview(w, "bob", NOW, 86400)
    assert p["ok"] is True
    assert p["target_claimer"] == "bob"
    assert p["from_claimer"] == "alice"
    # 预览必须列出当前 expires_at
    assert p["current_expires_at"] == EXP
    # 拍板语义：确认后重开满额，而非继承剩余 2 小时
    assert p["new_expires_at"] == (NOW + timedelta(seconds=86400)).isoformat()
    assert p["ttl_policy"] == "reset_full"
    # 预览不改 wishes
    assert w == snapshot


def test_preview_rejects_non_claimed():
    assert build_preview(claimed_wish(status="open", claimer=None, expires_at=None),
                         "bob", NOW, 86400)["reason"] == "not_claimed"
    assert build_preview(claimed_wish(status="fulfilled"), "bob", NOW, 86400)["reason"] == "not_claimed"


def test_preview_rejects_invalid_target():
    assert build_preview(claimed_wish(), "alice", NOW, 86400)["reason"] == "invalid_target"
    assert build_preview(claimed_wish(), "  ", NOW, 86400)["reason"] == "invalid_target"
    assert valid_target("alice", "bob")
    assert not valid_target("alice", "alice")
    assert not valid_target(None, "bob")
