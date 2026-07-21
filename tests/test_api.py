import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Point the app at a throwaway test DB before importing it, so test runs
# never depend on (or pollute) the real shortener.db used by `uvicorn`.
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_shortener.db")
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)

import app.database as database  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

database.engine = create_engine(
    f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False}
)
database.SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=database.engine
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_shorten_and_redirect():
    resp = client.post("/api/shorten", json={"url": "https://www.anthropic.com"})
    assert resp.status_code == 201
    data = resp.json()
    assert "short_code" in data
    assert data["original_url"] == "https://www.anthropic.com/"

    redirect_resp = client.get(f"/{data['short_code']}", follow_redirects=False)
    assert redirect_resp.status_code == 302
    assert redirect_resp.headers["location"] == "https://www.anthropic.com/"


def test_custom_code():
    resp = client.post(
        "/api/shorten",
        json={"url": "https://www.example.com", "custom_code": "myclaude"},
    )
    assert resp.status_code == 201
    assert resp.json()["short_code"] == "myclaude"

    # duplicate custom code should fail
    resp2 = client.post(
        "/api/shorten",
        json={"url": "https://www.example.org", "custom_code": "myclaude"},
    )
    assert resp2.status_code == 409


def test_404_for_unknown_code():
    resp = client.get("/does-not-exist-xyz")
    assert resp.status_code == 404


def test_stats_endpoint():
    resp = client.post("/api/shorten", json={"url": "https://www.aws.amazon.com"})
    short_code = resp.json()["short_code"]

    client.get(f"/{short_code}", follow_redirects=False)
    client.get(f"/{short_code}", follow_redirects=False)

    stats_resp = client.get(f"/api/stats/{short_code}")
    assert stats_resp.status_code == 200
    assert stats_resp.json()["total_clicks"] == 2
