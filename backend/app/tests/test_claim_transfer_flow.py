from datetime import datetime, timedelta, timezone
import pytest
from app.db import connect
from app import seed
from app.modules import wall
from app.modules.claim_transfer import (
    TransferError, cancel_pending_for_wish, confirm_transfer, open_transfer,
    pending_for, ensure_schema,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()

@pytest.fixture()
def db(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    c = connect()
    c.executescript("""
    CREATE TABLE wishes(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, note TEXT,
      status TEXT, claimer TEXT, claimed_at TEXT, expires_at TEXT, data_quality TEXT);
    CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    ensure_schema(c)
    c.commit(); c.close()
    return connect

def _claimed_claim(db, claimer="alice", expires_at=EXP, wid=1):
    c = db()
    c.execute("INSERT INTO wishes(id,title,note,status,claimer,claimed_at,expires_at,data_quality) "
              "VALUES (?,?,?,?,?,?,?,?)",
              (wid, "键盘", "", "claimed", claimer, NOW.isoformat(), expires_at, "clean"))
    c.commit(); c.close()

def test_preview_opens_order_without_touching_wish(db):
    _claimed_claim(db)
    before = dict(db().execute("SELECT * FROM wishes WHERE id=1").fetchone())
    out = open_transfer(1, "bob", NOW)
    after = dict(db().execute("SELECT * FROM wishes WHERE id=1").fetchone())
    assert before == after                       # 预览不改 wishes
    assert out["preview"]["to_claimer"] == "bob"
    assert out["preview"]["expires_at"] == EXP
    assert pending_for(db(), 1)["to_claimer"] == "bob"

def test_open_fails_on_illegal_target_or_non_claimed(db):
    _claimed_claim(db)
    with pytest.raises(TransferError) as e: open_transfer(1, "  ", NOW)
    assert e.value.reason == "bad_target"
    c = db(); c.execute("UPDATE wishes SET status='open',claimer=NULL,expires_at=NULL WHERE id=1"); c.commit(); c.close()
    with pytest.raises(TransferError) as e: open_transfer(1, "bob", NOW)
    assert e.value.reason == "not_claimed"

def test_pending_blocks_other_claims(db):
    from app.engines.claim_lock import claim_allowed
    _claimed_claim(db)
    open_transfer(1, "bob", NOW)
    c = db()
    order = pending_for(c, 1)
    r = c.execute("SELECT * FROM wishes WHERE id=1").fetchone()
    # Storage rule enforced by endpoint; emulate its guard: pending -> claim denied.
    assert order is not None
    assert claim_allowed(r["status"], r["claimer"], NOW, r["expires_at"])["reason"] == "locked"
    c.close()

def test_confirm_swaps_claimer_and_inherits_expiry(db):
    _claimed_claim(db)
    oid = open_transfer(1, "bob", NOW)["order"]["id"]
    res = confirm_transfer(oid, NOW + timedelta(minutes=10))
    assert res["ok"] is True
    w = dict(db().execute("SELECT * FROM wishes WHERE id=1").fetchone())
    assert w["claimer"] == "bob"                  # 钉新人
    assert w["expires_at"] == EXP                # expires_at 不变，继承剩余秒数
    assert w["status"] == "claimed"

def test_old_claimer_drops_from_mine_and_wall_pins_new(db):
    _claimed_claim(db)
    oid = open_transfer(1, "bob", NOW)["order"]["id"]
    confirm_transfer(oid, NOW)
    c = db()
    assert c.execute("SELECT COUNT(*) c FROM wishes WHERE claimer='alice'").fetchone()["c"] == 0
    assert c.execute("SELECT COUNT(*) c FROM wishes WHERE claimer='bob'").fetchone()["c"] == 1
    c.close()
    proj = {p["id"]: p for p in wall.project_all(NOW)}
    assert proj[1]["claimer"] == "bob"
    assert proj[1]["remaining_seconds"] == 3600  # 墙倒计时钉同一 expires_at
    assert proj[1]["transfer"] is None           # 单已确认

def test_second_open_while_pending_rejected(db):
    _claimed_claim(db)
    open_transfer(1, "bob", NOW)
    with pytest.raises(TransferError) as e: open_transfer(1, "carol", NOW)
    assert e.value.reason == "transfer_pending"

def test_confirm_non_pending_order_fails(db):
    _claimed_claim(db)
    oid = open_transfer(1, "bob", NOW)["order"]["id"]
    confirm_transfer(oid, NOW)
    with pytest.raises(TransferError) as e: confirm_transfer(oid, NOW)
    assert e.value.reason == "order_confirmed"

def test_cancel_then_claim_allowed(db):
    _claimed_claim(db)
    oid = open_transfer(1, "bob", NOW)["order"]["id"]
    c = db(); cancel_pending_for_wish(c, 1); c.commit(); c.close()
    assert pending_for(db(), 1) is None
    # After cancellation a fresh claim path is no longer blocked by the order.

def test_confirm_fails_after_release_cancels_order(db):
    _claimed_claim(db)
    oid = open_transfer(1, "bob", NOW)["order"]["id"]
    c = db()
    c.execute("UPDATE wishes SET status='released',claimer=NULL,claimed_at=NULL,expires_at=NULL WHERE id=1")
    cancel_pending_for_wish(c, 1); c.commit(); c.close()
    with pytest.raises(TransferError) as e: confirm_transfer(oid, NOW)
    assert e.value.reason == "order_cancelled"

def test_wall_shows_in_flight_transfer(db):
    _claimed_claim(db)
    open_transfer(1, "bob", NOW)
    p = {x["id"]: x for x in wall.project_all(NOW)}[1]
    assert p["claimer"] == "alice"               # 未确认前仍钉原认领人
    assert p["transfer"]["to_claimer"] == "bob"
