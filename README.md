# scalable-url-shortener

A URL shortener with the pieces that usually get skipped in a quick CRUD demo:
caching, rate limiting, click analytics, and ID generation that doesn't rely
on retrying after collisions. Built mainly as a system design reference for
backend interviews, but it runs as a real service.

## Features

- Shorten and redirect: `POST /api/shorten`, `GET /{code}`, with optional
  custom vanity codes
- Redis cache with an in-memory LRU fallback when Redis isn't available, so
  redirects skip the DB on a cache hit (look for the `X-Cache: HIT/MISS`
  header)
- Per-IP rate limiting via a token bucket (burst + sustained rate), implemented
  as ASGI middleware
- Click logging (timestamp, referrer, hashed IP), queryable through
  `GET /api/stats/{code}`
- Short codes are base62-encoded from the DB auto-increment ID rather than
  generated randomly, so there's no collision retry loop under concurrent
  writes
- Load test script for measuring real throughput and latency

## Architecture

```
Client -> [Rate Limiter Middleware] -> FastAPI
                                          |
                          cache hit? -----+----- cache miss?
                             |                        |
                        return cached URL      query SQLite/Postgres
                             |                        |
                        (async) log click        cache the result
                             |                        |
                        302 redirect  <---------------+
```

On AWS this would map to API Gateway + Lambda (or ECS), DynamoDB or RDS for
storage, ElastiCache for the cache layer, and SQS to keep click logging off
the redirect path.

## Project structure

```
scalable-url-shortener/
├── app/
│   ├── main.py          # API routes
│   ├── models.py        # DB tables (URL, Click)
│   ├── schemas.py        # Pydantic request/response models
│   ├── database.py        # SQLAlchemy engine/session setup
│   ├── cache.py           # Redis / in-memory LRU cache
│   └── rate_limiter.py    # Token bucket middleware
├── tests/
│   └── test_api.py        # pytest suite
├── load_test.py           # concurrency/latency benchmark
├── requirements.txt
├── Dockerfile
└── docker-compose.yml     # app + Redis
```

## Setup

Requires Python 3.10+.

### Local, no Redis

```bash
cd scalable-url-shortener
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload
```

API runs at `http://127.0.0.1:8000`, docs at `http://127.0.0.1:8000/docs`.
Without Redis, the cache falls back to in-memory LRU — everything still
works, but the cache doesn't survive a restart.

### Docker Compose (with Redis)

Requires Docker.

```bash
cd scalable-url-shortener
docker-compose up --build
```

Starts the app on port 8000 and a Redis instance, connected via `REDIS_URL`.

## Usage

```bash
# Shorten a URL
curl -X POST http://127.0.0.1:8000/api/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.example.com"}'
# -> {"short_code": "1", "short_url": "http://127.0.0.1:8000/1", ...}

# Follow the redirect
curl -i http://127.0.0.1:8000/1

# Check analytics
curl http://127.0.0.1:8000/api/stats/1

# Custom vanity code
curl -X POST http://127.0.0.1:8000/api/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.example.com", "custom_code": "my-page"}'
```

Or use the Swagger UI at `/docs` to hit the endpoints from the browser.

## Tests

```bash
pytest tests/ -v
```

## Benchmarking

With the server running:

```bash
python load_test.py --requests 500 --concurrency 20
```

Prints throughput (req/sec) and p50/p95/p99 latency for your local setup.

## Deploying to AWS

- Package as a container for ECS Fargate, or adapt for Lambda behind API
  Gateway
- Replace SQLite with DynamoDB (partition key = `short_code`) or RDS
- Replace the Redis fallback with a real ElastiCache cluster
- Add CloudWatch logging/metrics and an alarm on error rate
