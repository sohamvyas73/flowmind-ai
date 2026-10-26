import time
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.ratelimit import limiter
from app.main import app
from app.models.user import User

client = TestClient(app)
_n = 0

SIMPLE_GRAPH = {
    "nodes": [
        {"id": "in", "type": "inputNode", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "t", "type": "transformNode", "position": {"x": 1, "y": 0}, "data": {}},
        {"id": "out", "type": "outputNode", "position": {"x": 2, "y": 0}, "data": {}},
    ],
    "edges": [
        {"id": "e1", "source": "in", "target": "t"},
        {"id": "e2", "source": "t", "target": "out"},
    ],
}


def signup(activate=True, credits=None):
    """Create a user. Returns (email, signup_body, auth headers)."""
    global _n
    _n += 1
    limiter.reset()
    email = f"p1user{_n}_{time.time_ns()}@example.com"
    r = client.post("/api/v1/auth/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    body = r.json()
    db = SessionLocal()
    u = db.query(User).filter(User.email == email).first()
    u.is_active = activate
    if credits is not None:
        u.credits_total = credits
    db.commit()
    db.close()
    return email, body, {"Authorization": f"Bearer {body['access_token']}"}


def admin_headers():
    limiter.reset()
    r = client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "admin-pass-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def create_workflow(headers, graph=None, name="wf"):
    r = client.post("/api/v1/workflows/workflows", json={"name": name, "graph_data": graph or SIMPLE_GRAPH}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def credits_used(email):
    db = SessionLocal()
    used = db.query(User).filter(User.email == email).first().credits_used
    db.close()
    return used


def reset_jobs():
    """Isolate tests that drive the worker/scheduler: nothing from other tests may be claimable."""
    from sqlalchemy import text
    db = SessionLocal()
    db.execute(text("DELETE FROM jobs"))
    db.execute(text("DELETE FROM schedules"))
    db.commit()
    db.close()


def uuid_(s):
    return UUID(str(s))
