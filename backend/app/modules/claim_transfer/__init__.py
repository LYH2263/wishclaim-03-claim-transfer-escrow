"""Claim-transfer storage + orchestration.

A pending transfer order is a托管单: it records from/to for a claimed wish but
does NOT mutate ``wishes`` until confirmed. Confirm runs in a single
``BEGIN IMMEDIATE`` transaction so it is atomic against a competing claim.
TTL on confirm is inherited (expires_at untouched) — see engines.transfer_lock.
"""
from app.db import connect, write_tx
from app.engines.transfer_lock import confirm_plan, transfer_preview

SCHEMA = """
CREATE TABLE IF NOT EXISTS transfers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wish_id INTEGER NOT NULL,
  from_claimer TEXT NOT NULL,
  to_claimer TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_transfers_one_pending
  ON transfers(wish_id) WHERE status='pending';
"""

def ensure_schema(c):
    c.executescript(SCHEMA)

def _order_dict(r):
    return dict(r) if r else None

def pending_for(c, wish_id: int) -> dict | None:
    r = c.execute(
        "SELECT * FROM transfers WHERE wish_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
        (wish_id,),
    ).fetchone()
    return _order_dict(r)

def pending_map(c, wish_ids: list[int] | None = None) -> dict:
    """Map wish_id -> pending order for projection."""
    if wish_ids is not None and len(wish_ids) == 0:
        return {}
    q = "SELECT * FROM transfers WHERE status='pending'"
    rows = c.execute(q).fetchall() if wish_ids is None else c.execute(
        q + " AND wish_id IN (%s)" % ",".join("?" * len(wish_ids)), wish_ids
    ).fetchall()
    return {r["wish_id"]: _order_dict(r) for r in rows}

def get_order(c, order_id: int) -> dict | None:
    return _order_dict(c.execute("SELECT * FROM transfers WHERE id=?", (order_id,)).fetchone())

def cancel_pending_for_wish(c, wish_id: int) -> int:
    """Invalidate a托管单 when the lock underneath it vanishes (TTL/release)."""
    cur = c.execute(
        "UPDATE transfers SET status='cancelled' WHERE wish_id=? AND status='pending'",
        (wish_id,),
    )
    return cur.rowcount

class TransferError(Exception):
    def __init__(self, reason: str, code: int = 409):
        super().__init__(reason)
        self.reason = reason
        self.code = code

def open_transfer(wish_id: int, target: str | None, now) -> dict:
    """Preview then persist a pending order. Never modifies ``wishes``."""
    with write_tx() as c:
        w = c.execute("SELECT * FROM wishes WHERE id=?", (wish_id,)).fetchone()
        if not w:
            raise TransferError("not_found", 404)
        pv = transfer_preview(w["status"], w["claimer"], w["expires_at"], target)
        if not pv["ok"]:
            raise TransferError(pv["reason"], 400 if pv["reason"] == "bad_target" else 409)
        if pending_for(c, wish_id):
            raise TransferError("transfer_pending", 409)
        cur = c.execute(
            "INSERT INTO transfers(wish_id,from_claimer,to_claimer,status,created_at) "
            "VALUES (?,?,?,'pending',?)",
            (wish_id, w["claimer"], pv["preview"]["to_claimer"], now.isoformat()),
        )
        order = get_order(c, cur.lastrowid)
    return {"order": order, "preview": pv["preview"]}

def confirm_transfer(order_id: int, now) -> dict:
    """Swap claimer -> target under a write lock; expires_at is inherited."""
    with write_tx() as c:
        order = get_order(c, order_id)
        if not order:
            raise TransferError("not_found", 404)
        if order["status"] != "pending":
            raise TransferError("order_%s" % order["status"], 409)
        w = c.execute("SELECT * FROM wishes WHERE id=?", (order["wish_id"],)).fetchone()
        if not w:
            raise TransferError("not_found", 404)
        plan = confirm_plan(
            w["status"], w["claimer"], w["expires_at"],
            order["from_claimer"], order["to_claimer"], now,
        )
        if not plan["ok"]:
            # Wish drifted (TTL reclaim / release) — the stale order dies.
            if plan["reason"] in ("not_claimed", "ttl_expired", "claimer_changed"):
                c.execute("UPDATE transfers SET status='cancelled' WHERE id=?", (order_id,))
            raise TransferError(plan["reason"], 409 if plan["reason"] != "bad_target" else 400)
        # expires_at intentionally NOT updated: remaining TTL is inherited.
        c.execute("UPDATE wishes SET claimer=? WHERE id=?",
                  (plan["patch"]["claimer"], w["id"]))
        c.execute("UPDATE transfers SET status='confirmed' WHERE id=?", (order_id,))
        wish = dict(c.execute("SELECT * FROM wishes WHERE id=?", (w["id"],)).fetchone())
    return {"ok": True, "wish": wish, "ttl_policy": "inherit_remaining"}

def cancel_transfer(order_id: int) -> dict:
    with write_tx() as c:
        order = get_order(c, order_id)
        if not order:
            raise TransferError("not_found", 404)
        if order["status"] != "pending":
            raise TransferError("order_%s" % order["status"], 409)
        c.execute("UPDATE transfers SET status='cancelled' WHERE id=?", (order_id,))
    return {"ok": True, "status": "cancelled"}
