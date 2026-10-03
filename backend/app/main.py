from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect, write_tx
from app.engines.claim_lock import claim_allowed, lock_payload, release_if_expired
from app.modules import wall
from app.modules.claim_transfer import (
    TransferError, cancel_transfer, confirm_transfer, open_transfer,
    pending_for, cancel_pending_for_wish,
)

app = FastAPI(title="Wishclaim", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

def now(): return datetime.now(timezone.utc)

def ttl():
    c = connect(); row = c.execute("SELECT value FROM settings WHERE key='ttl_seconds'").fetchone(); c.close()
    return int(row["value"] if row else 86400)

def sweep(c):
    """Release expired locks; any托管单 pinned to a vanished lock is cancelled."""
    for r in c.execute("SELECT * FROM wishes WHERE status='claimed'"):
        rel = release_if_expired(r["status"], r["expires_at"], now())
        if rel:
            c.execute("UPDATE wishes SET status=?, claimer=?, claimed_at=?, expires_at=? WHERE id=?",
                      (rel["status"], None, None, None, r["id"]))
            cancel_pending_for_wish(c, r["id"])

def _sweep_committed():
    with write_tx() as c:
        sweep(c)

def _transfer_error(e: TransferError):
    return HTTPException(e.code, e.reason)

@app.get("/api/health")
def health(): return {"ok": True, "project": "wishclaim"}

@app.get("/api/wishes")
def list_wishes():
    _sweep_committed()
    return wall.project_all(now())

@app.get("/api/wishes/{wid}")
def get_wish(wid: int):
    _sweep_committed()
    p = wall.project_one(wid, now())
    if not p: raise HTTPException(404, "not found")
    return p

class WishIn(BaseModel):
    title: str
    note: str = ""

@app.post("/api/wishes")
def create_wish(body: WishIn):
    c = connect()
    cur = c.execute("INSERT INTO wishes(title,note,status,data_quality) VALUES (?,?,?,?)",
                    (body.title, body.note, "open", "clean"))
    c.commit(); wid = cur.lastrowid; c.close(); return {"id": wid}

class ClaimIn(BaseModel):
    claimer: str

@app.post("/api/wishes/{wid}/claim")
def claim(wid: int, body: ClaimIn):
    _sweep_committed()
    with write_tx() as c:
        r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
        if not r: raise HTTPException(404, "not found")
        if pending_for(c, wid):
            # An in-flight (unconfirmed) transfer freezes the row for others.
            raise HTTPException(409, "transfer_in_progress")
        allowed = claim_allowed(r["status"], r["claimer"], now(), r["expires_at"])
        if not allowed["ok"]:
            raise HTTPException(409, allowed["reason"])
        p = lock_payload(body.claimer, now(), ttl())
        c.execute("UPDATE wishes SET status=?, claimer=?, claimed_at=?, expires_at=? WHERE id=?",
                  (p["status"], p["claimer"], p["claimed_at"], p["expires_at"], wid))
    return p

@app.post("/api/wishes/{wid}/release")
def release(wid: int):
    with write_tx() as c:
        r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
        if not r: raise HTTPException(404, "not found")
        if r["status"] != "claimed":
            raise HTTPException(400, "not_claimed")
        c.execute("UPDATE wishes SET status='released', claimer=NULL, claimed_at=NULL, expires_at=NULL WHERE id=?", (wid,))
        cancel_pending_for_wish(c, wid)
    return {"ok": True, "status": "released"}

@app.post("/api/wishes/{wid}/fulfill")
def fulfill(wid: int):
    with write_tx() as c:
        r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
        if not r: raise HTTPException(404, "not found")
        if r["status"] != "claimed":
            raise HTTPException(400, "need_claim")
        c.execute("UPDATE wishes SET status='fulfilled' WHERE id=?", (wid,))
        cancel_pending_for_wish(c, wid)
    return {"ok": True, "status": "fulfilled"}

class TransferIn(BaseModel):
    target: str

@app.post("/api/wishes/{wid}/transfers")
def create_transfer(wid: int, body: TransferIn):
    """Preview target person + current expires_at, then open a pending托管单.
    The wish row is not modified."""
    try:
        return open_transfer(wid, body.target, now())
    except TransferError as e:
        raise _transfer_error(e)

@app.post("/api/transfers/{order_id}/confirm")
def confirm(order_id: int):
    """Confirm a托管单: claimer becomes the target; expires_at is inherited."""
    try:
        return confirm_transfer(order_id, now())
    except TransferError as e:
        raise _transfer_error(e)

@app.post("/api/transfers/{order_id}/cancel")
def cancel(order_id: int):
    try:
        return cancel_transfer(order_id)
    except TransferError as e:
        raise _transfer_error(e)

@app.get("/api/mine")
def mine(claimer: str):
    _sweep_committed()
    c = connect()
    rows = [dict(r) for r in c.execute("SELECT * FROM wishes WHERE claimer=?", (claimer,))]
    c.close()
    # After a confirmed transfer the old claimer no longer owns the row:
    # claimer now equals the target, so this query naturally drops it.
    return rows

@app.get("/api/done")
def done():
    c = connect()
    rows = [dict(r) for r in c.execute("SELECT * FROM wishes WHERE status='fulfilled'")]; c.close(); return rows

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows

@app.get("/api/rules")
def rules():
    return {
        "mutex": "同一愿望同时只能被一人认领",
        "ttl": "认领超时未核销则自动释放",
        "fulfill": "核销后状态变为 fulfilled",
        "transfer": "claimed 可由当前认领人发起转让托管：预览目标人与当前 expires_at，确认后认领人变为目标人",
        "ttl_transfer": "转让继承剩余秒数：确认时 expires_at 不变，不重开满额 TTL；墙倒计时与详情到期时间同钉",
        "transfer_mutex": "存在进行中未确认的转让单时，他人 claim 失败",
    }
