"""Protection for the AI ask box (Phase 11).

- Off unless ASK_ACCESS_CODE is set: a Claude key alone never opens a public,
  billable endpoint.
- Every question must carry the code (X-Access-Code header).
- Per-visitor rate limit: ASK_RATE_PER_HOUR questions per rolling hour
  (default 20). In memory, so it is per server instance: a soft limit. The
  hard ceiling is the spend limit on the Anthropic account.
- Visitors are identified by a salted hash of their IP; raw IPs are never
  stored or logged.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

WINDOW_S = 3600
_hits: dict[str, deque[float]] = defaultdict(deque)
_SALT = os.urandom(16)  # per process: hashes can't be linked across restarts


def visitor_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return hashlib.sha256(_SALT + ip.encode()).hexdigest()[:16]


def check_access(request: Request) -> str:
    """Raise if the ask box is off, the code is wrong, or the visitor is over the limit. Returns the visitor id."""
    code = os.getenv("ASK_ACCESS_CODE", "")
    if not code:
        raise HTTPException(status_code=503, detail="The AI ask box isn't enabled on this deployment.")
    given = request.headers.get("x-access-code", "")
    if not hmac.compare_digest(given.encode(), code.encode()):
        raise HTTPException(status_code=401, detail="Access code required for the AI ask box.")
    vid = visitor_id(request)
    limit = int(os.getenv("ASK_RATE_PER_HOUR", "20"))
    now = time.monotonic()
    q = _hits[vid]
    while q and now - q[0] > WINDOW_S:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail=f"Limit of {limit} questions an hour reached. Try again later.")
    q.append(now)
    return vid
