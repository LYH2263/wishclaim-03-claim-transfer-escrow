"""Wall projection: turn a wish row (+ pending transfer) into wall/detail data.

The wall card and detail page must show the same pinned facts: who the claim
nails to, the running-down TTL, and any in-flight transfer. This is a pure
function of stored state so every surface stays in lockstep.
"""
from datetime import datetime
from app.engines.claim_lock import parse_ts

def project_wish(wish: dict, now: datetime, transfer: dict | None = None) -> dict:
    """Return a projection of one wish.

    ``transfer`` is the live pending transfer row (or None). Adds:
      - remaining_seconds: TTL countdown (None when not claimed/expiring)
      - transfer: {id, from_claimer, to_claimer} when an order is in flight
    The claimer shown is always the wish row's current claimer, so after a
    confirmed transfer wall and detail pin the new person at once.
    """
    p = dict(wish)
    p["remaining_seconds"] = None
    if wish.get("status") == "claimed" and wish.get("expires_at"):
        delta = (parse_ts(wish["expires_at"]) - now).total_seconds()
        p["remaining_seconds"] = max(0, int(delta))
    if transfer:
        p["transfer"] = {
            "id": transfer["id"],
            "wish_id": transfer["wish_id"],
            "from_claimer": transfer["from_claimer"],
            "to_claimer": transfer["to_claimer"],
        }
    else:
        p["transfer"] = None
    return p
