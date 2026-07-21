"""
Scalable URL Shortener API.

Endpoints:
  POST /api/shorten       -> create a short URL
  GET  /{short_code}      -> redirect to original URL (cached, rate-limited)
  GET  /api/stats/{code}  -> click analytics for a short code
  GET  /health            -> health check
  GET  /api/cache-info     -> which cache backend is active

Run with: uvicorn app.main:app --reload
"""
import hashlib
import string
import time
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy.orm import Session

from . import cache, models, schemas
from .database import Base, engine, get_db
from .rate_limiter import RateLimitMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Scalable URL Shortener",
    description="A URL shortener with caching, rate limiting, and click analytics.",
    version="1.0.0",
)

# Burst of 20 requests, sustained 5 req/sec per IP — tune for your load test
app.add_middleware(RateLimitMiddleware, capacity=20, refill_rate_per_sec=5.0)

BASE62_ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase
CODE_LENGTH = 7


def encode_base62(num: int) -> str:
    """Encode an integer id into a base62 string. Collision-free by
    construction since it's derived from the DB auto-increment id, not
    randomly generated (avoids the classic 'random code collides' retry
    loop under high write concurrency)."""
    if num == 0:
        return BASE62_ALPHABET[0]
    chars = []
    base = len(BASE62_ALPHABET)
    while num > 0:
        num, rem = divmod(num, base)
        chars.append(BASE62_ALPHABET[rem])
    return "".join(reversed(chars)).rjust(CODE_LENGTH, "0")


@app.post("/api/shorten", response_model=schemas.URLResponse, status_code=201)
def shorten_url(
    payload: schemas.URLCreateRequest, request: Request, db: Session = Depends(get_db)
):
    original_url = str(payload.url)

    if payload.custom_code:
        existing = (
            db.query(models.URL)
            .filter(models.URL.short_code == payload.custom_code)
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Custom code already taken")
        short_code = payload.custom_code
        db_url = models.URL(short_code=short_code, original_url=original_url)
        db.add(db_url)
        db.commit()
        db.refresh(db_url)
    else:
        # Insert first to get an auto-increment id, then derive the code
        # from that id and update the row. Two small writes, but no
        # collision retries — a good tradeoff to be ready to defend.
        db_url = models.URL(short_code="", original_url=original_url)
        db.add(db_url)
        db.commit()
        db.refresh(db_url)
        db_url.short_code = encode_base62(db_url.id)
        db.commit()
        db.refresh(db_url)

    cache.cache_set(db_url.short_code, db_url.original_url)

    base_url = str(request.base_url).rstrip("/")
    return schemas.URLResponse(
        short_code=db_url.short_code,
        short_url=f"{base_url}/{db_url.short_code}",
        original_url=db_url.original_url,
        created_at=db_url.created_at,
    )

@app.get("/api/cache-info")
def cache_info():
    return {"backend": cache.backend_name()}


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# NOTE: this catch-all route MUST be declared last. FastAPI/Starlette match
# routes in declaration order, so a broad path param like /{short_code}
# would otherwise swallow specific routes like /health or /api/... that are
# declared after it. This is a common gotcha worth knowing for interviews.
@app.get("/{short_code}")
def redirect_to_original(
    short_code: str, request: Request, db: Session = Depends(get_db)
):
    from fastapi.responses import RedirectResponse

    original_url = cache.cache_get(short_code)
    cache_hit = original_url is not None

    if not original_url:
        db_url = (
            db.query(models.URL).filter(models.URL.short_code == short_code).first()
        )
        if not db_url:
            raise HTTPException(status_code=404, detail="Short URL not found")
        original_url = db_url.original_url
        cache.cache_set(short_code, original_url)
    else:
        db_url = (
            db.query(models.URL).filter(models.URL.short_code == short_code).first()
        )

    # Log the click asynchronously-ish: this write should never block the
    # redirect response in a real system (you'd push to a queue like SQS
    # and have a worker consume it). Kept synchronous here for simplicity.
    client_ip = request.client.host if request.client else "unknown"
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
    click = models.Click(
        url_id=db_url.id,
        referrer=request.headers.get("referer"),
        ip_hash=ip_hash,
    )
    db.add(click)
    db.commit()

    response = RedirectResponse(url=original_url, status_code=302)
    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"
    return response


@app.get("/api/stats/{short_code}", response_model=schemas.StatsResponse)
def get_stats(short_code: str, db: Session = Depends(get_db)):
    db_url = db.query(models.URL).filter(models.URL.short_code == short_code).first()
    if not db_url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    total_clicks = (
        db.query(models.Click).filter(models.Click.url_id == db_url.id).count()
    )
    recent = (
        db.query(models.Click)
        .filter(models.Click.url_id == db_url.id)
        .order_by(models.Click.timestamp.desc())
        .limit(20)
        .all()
    )

    return schemas.StatsResponse(
        short_code=db_url.short_code,
        original_url=db_url.original_url,
        total_clicks=total_clicks,
        created_at=db_url.created_at,
        recent_clicks=[
            schemas.ClickEvent(timestamp=c.timestamp, referrer=c.referrer)
            for c in recent
        ],
    )



