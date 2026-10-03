import sqlite3
from datetime import datetime, timedelta, timezone
import pytest

from app.modules.claim_transfer import locking as L

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
TTL = 86400


@pytest.fixture()
def c():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE wishes(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, note TEXT, status TEXT,
      claimer TEXT, claimed_at TEXT, expires_at TEXT, data_quality TEXT
    );
    """)
    conn.executescript(L.SCHEMA)
    conn.execute(
        "INSERT INTO wishes(title,status,claimer,claimed_at,expires_at,data_quality)"
        " VALUES ('键盘','claimed','alice',?,?,'clean')",
        ((NOW - timedelta(hours=1)).isoformat(), (NOW + timedelta(hours=2)).isoformat()),
    )
    conn.execute("INSERT INTO wishes(title,status,data_quality) VALUES ('围巾','open','clean')")
    conn.commit()
    yield conn
    conn.close()


def _wish(c, wid=1):
    return dict(c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone())


def test_offer_creates_pending_without_touching_wishes(c):
    before = _wish(c)
    res = L.offer_transfer(c, 1, "alice", "bob", NOW, TTL)
    assert res["ok"] is True
    assert res["current_expires_at"] == before["expires_at"]
    assert res["new_expires_at"] == (NOW + timedelta(seconds=TTL)).isoformat()
    after = _wish(c)
    assert after == before  # 发起/预览不改 wishes
    p = L.pending_for_wish(c, 1)
    assert p["from_claimer"] == "alice" and p["target_claimer"] == "bob"


def test_offer_guards(c):
    assert L.offer_transfer(c, 2, None, "bob", NOW, TTL)["reason"] == "not_claimed"
    assert L.offer_transfer(c, 1, "carol", "bob", NOW, TTL)["reason"] == "not_owner"
    assert L.offer_transfer(c, 1, "alice", "alice", NOW, TTL)["reason"] == "invalid_target"
    assert L.offer_transfer(c, 1, "alice", "  ", NOW, TTL)["reason"] == "invalid_target"
    assert L.offer_transfer(c, 99, "alice", "bob", NOW, TTL)["reason"] == "not_found"


def test_only_one_pending_offer_per_wish(c):
    assert L.offer_transfer(c, 1, "alice", "bob", NOW, TTL)["ok"]
    assert L.offer_transfer(c, 1, "alice", "carol", NOW, TTL)["reason"] == "pending_transfer"


def test_pending_offer_blocks_other_claims(c):
    L.offer_transfer(c, 1, "alice", "bob", NOW, TTL)
    blocked = L.claim_blocked_by_pending(c, 1, "carol")
    assert blocked["reason"] == "pending_transfer"
    assert blocked["pending"]["target_claimer"] == "bob"


def test_confirm_swaps_claimer_and_resets_full_ttl(c):
    offer = L.offer_transfer(c, 1, "alice", "bob", NOW, TTL)
    res = L.confirm_transfer(c, offer["id"], "bob", NOW, TTL)
    assert res["ok"] is True
    w = _wish(c)
    # 钉新人：claimer 变目标人，claimed_at/expires_at 以确认时刻重开
    assert w["claimer"] == "bob"
    assert w["claimed_at"] == NOW.isoformat()
    assert w["expires_at"] == (NOW + timedelta(seconds=TTL)).isoformat()
    assert res["ttl_policy"] == "reset_full"
    t = c.execute("SELECT status FROM claim_transfers WHERE id=?", (offer["id"],)).fetchone()
    assert t["status"] == "confirmed"
    # 原认领人不再有 pending/托管
    assert L.pending_for_wish(c, 1) is None


def test_confirm_requires_target_and_pending(c):
    offer = L.offer_transfer(c, 1, "alice", "bob", NOW, TTL)
    # 非目标人确认失败
    assert L.confirm_transfer(c, offer["id"], "carol", NOW, TTL)["reason"] == "not_target"
    # 愿望仍归 alice，未被改动
    assert _wish(c)["claimer"] == "alice"
    # 目标人确认成功后，重复确认失败
    assert L.confirm_transfer(c, offer["id"], "bob", NOW, TTL)["ok"]
    assert L.confirm_transfer(c, offer["id"], "bob", NOW, TTL)["reason"] == "transfer_not_pending"


def test_confirm_fails_when_wish_not_claimed(c):
    offer = L.offer_transfer(c, 1, "alice", "bob", NOW, TTL)
    # 转让期间愿望被释放/核销，确认必须失败
    c.execute("UPDATE wishes SET status='released', claimer=NULL WHERE id=1")
    c.commit()
    assert L.confirm_transfer(c, offer["id"], "bob", NOW, TTL)["reason"] == "wish_not_claimed"
    assert L.pending_for_wish(c, 1) is not None  # 未确认单仍在，需 sweep/显式过期


def test_confirm_fails_for_illegal_target_row(c):
    # 手工塞入目标人=原认领人的非法单，确认侧也要挡住
    cur = c.execute(
        "INSERT INTO claim_transfers(wish_id,from_claimer,target_claimer,status,created_at)"
        " VALUES (1,'alice','alice','pending',?)", (NOW.isoformat(),))
    assert L.confirm_transfer(c, cur.lastrowid, "alice", NOW, TTL)["reason"] == "invalid_target"
    assert _wish(c)["claimer"] == "alice"


def test_cancel_releases_escrow(c):
    offer = L.offer_transfer(c, 1, "alice", "bob", NOW, TTL)
    assert L.cancel_transfer(c, offer["id"], "carol")["reason"] == "not_owner"
    assert L.cancel_transfer(c, offer["id"], "alice")["ok"]
    assert L.claim_blocked_by_pending(c, 1, "carol") is None
    # 撤销后再确认失败
    assert L.confirm_transfer(c, offer["id"], "bob", NOW, TTL)["reason"] == "transfer_not_pending"


def test_sweep_expires_offer_with_released_or_ttl_expired_wish(c):
    offer = L.offer_transfer(c, 1, "alice", "bob", NOW, TTL)
    c.execute("UPDATE wishes SET status='released', claimer=NULL, expires_at=NULL WHERE id=1")
    c.commit()
    assert L.expire_pending_transfers(c, NOW) == 1
    t = c.execute("SELECT status FROM claim_transfers WHERE id=?", (offer["id"],)).fetchone()
    assert t["status"] == "expired"
    assert L.claim_blocked_by_pending(c, 1, "carol") is None


def test_expire_pending_on_ttl_past(c):
    offer = L.offer_transfer(c, 1, "alice", "bob", NOW, TTL)
    later = NOW + timedelta(hours=3)  # 超过当前 expires_at（NOW+2h）
    assert L.expire_pending_transfers(c, later) == 1
    assert L.pending_for_wish(c, 1) is None
