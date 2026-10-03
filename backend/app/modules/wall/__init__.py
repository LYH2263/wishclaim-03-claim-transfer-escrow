"""Wall read model: project wish rows together with pending transfers."""
from app.db import connect
from app.engines.wall_projection import project_wish
from app.modules.claim_transfer import pending_map

def project_all(now) -> list[dict]:
    c = connect()
    try:
        rows = [dict(r) for r in c.execute("SELECT * FROM wishes ORDER BY id DESC")]
        pmap = pending_map(c, [r["id"] for r in rows])
    finally:
        c.close()
    return [project_wish(r, now, pmap.get(r["id"])) for r in rows]

def project_one(wish_id: int, now) -> dict | None:
    c = connect()
    try:
        r = c.execute("SELECT * FROM wishes WHERE id=?", (wish_id,)).fetchone()
        if not r:
            return None
        order = pending_map(c, [wish_id]).get(wish_id)
    finally:
        c.close()
    return project_wish(dict(r), now, order)
