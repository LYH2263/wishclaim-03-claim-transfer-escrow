"""Claim transfer (托管转让) pure rules.

A claimed wish can be handed from its current claimer to a target person.
The transfer order is created as *pending*; it does not touch ``wishes``.
Only on confirm does the claimer change. TTL policy is pinned here:

    继承剩余秒数 —— the wish's ``expires_at`` is carried over unchanged;
    transferring never refreshes the TTL.
"""
from datetime import datetime
from app.engines.claim_lock import parse_ts

# Target must be a real, non-empty person; blanks/whitespace are illegal.
def normalize_target(target: str | None) -> str | None:
    if target is None:
        return None
    t = target.strip()
    return t or None

def valid_target(target: str | None) -> bool:
    return normalize_target(target) is not None

def transfer_preview(status: str, claimer: str | None, expires_at: str | None,
                     target: str | None) -> dict:
    """Build a transfer preview without mutating anything.

    Returns ``{ok, reason, preview}``; on success ``preview`` carries the
    target person and the *current* expires_at (the value that will be
    inherited on confirm).
    """
    if status != "claimed":
        return {"ok": False, "reason": "not_claimed", "preview": None}
    if not claimer:
        return {"ok": False, "reason": "not_claimed", "preview": None}
    t = normalize_target(target)
    if t is None:
        return {"ok": False, "reason": "bad_target", "preview": None}
    if t == claimer:
        return {"ok": False, "reason": "target_is_self", "preview": None}
    return {
        "ok": True,
        "reason": "",
        "preview": {
            "from_claimer": claimer,
            "to_claimer": t,
            "expires_at": expires_at,
            "ttl_policy": "inherit_remaining",
        },
    }

def confirm_plan(wish_status: str, current_claimer: str | None, expires_at: str | None,
                 order_from: str, order_to: str, now: datetime) -> dict:
    """Validate a pending order against the *current* wish row at confirm time.

    On success returns ``{ok, patch}`` where ``patch`` only swaps the claimer —
    ``expires_at`` is deliberately absent so the remaining TTL is inherited.
    """
    if wish_status != "claimed" or not current_claimer:
        return {"ok": False, "reason": "not_claimed"}
    if current_claimer != order_from:
        # Wish moved (TTL reclaim / release) since the order was opened.
        return {"ok": False, "reason": "claimer_changed"}
    if expires_at and parse_ts(expires_at) <= now:
        return {"ok": False, "reason": "ttl_expired"}
    if not valid_target(order_to) or order_to == order_from:
        return {"ok": False, "reason": "bad_target"}
    return {
        "ok": True,
        "reason": "",
        "patch": {"claimer": order_to, "ttl_policy": "inherit_remaining"},
    }
