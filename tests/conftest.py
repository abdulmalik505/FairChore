"""
Shared pytest fixtures for FairChore test suite.

Sets up a temporary PostgreSQL test database (fairchore_test) for API and DB
tests, so the main fairchore database is never touched during testing.

Architecture:
  - session scope: create fairchore_test DB + schema once per pytest run
  - function scope: truncate all tables before each test (clean slate)
  - Fixtures: client (Flask test client), db (raw psycopg2 connection), helpers
"""

import os
import sys
import json
import pytest
import psycopg2

# ── Must set env vars BEFORE importing backend.app, because app.py reads them
#    at module level. load_dotenv() will NOT override already-set vars.
_PROD_DB = "postgresql://postgres:REDACTED@localhost:5432/fairchore"
_TEST_DB = "postgresql://postgres:REDACTED@localhost:5432/fairchore_test"
_POSTGRES_ADMIN_DB = "postgresql://postgres:REDACTED@localhost:5432/postgres"

os.environ.setdefault("DATABASE_URL", _TEST_DB)
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app as flask_app  # noqa: E402 (must come after env setup)

# ── DDL only (no seed data) applied to fairchore_test ────────────────────────

_SCHEMA_DDL = """
DROP TABLE IF EXISTS allocation_results CASCADE;
DROP TABLE IF EXISTS assignment_history CASCADE;
DROP TABLE IF EXISTS burden_scores CASCADE;
DROP TABLE IF EXISTS chores CASCADE;
DROP TABLE IF EXISTS household_members CASCADE;
DROP TABLE IF EXISTS households CASCADE;
DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(512),
    total_burden_accumulated NUMERIC(12,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE households (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    join_code VARCHAR(10) UNIQUE NOT NULL,
    admin_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE household_members (
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (household_id, user_id)
);

CREATE TABLE chores (
    id SERIAL PRIMARY KEY,
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE burden_scores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    chore_id INTEGER REFERENCES chores(id) ON DELETE CASCADE,
    score INTEGER DEFAULT 0,
    is_capable BOOLEAN DEFAULT TRUE,
    UNIQUE(user_id, chore_id)
);

CREATE TABLE assignment_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    chore_id INTEGER REFERENCES chores(id),
    burden_at_time NUMERIC(10,2),
    algorithm_used VARCHAR(50),
    date_assigned TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP NULL DEFAULT NULL
);

CREATE TABLE allocation_results (
    id SERIAL PRIMARY KEY,
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    round_ts TIMESTAMP UNIQUE NOT NULL,
    algorithm VARCHAR(50),
    scores_json JSONB NOT NULL DEFAULT '{}',
    metrics_json JSONB NOT NULL DEFAULT '{}'
);
"""

# ── Session-scoped: create test DB + schema once per pytest run ───────────────

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    admin = psycopg2.connect(_POSTGRES_ADMIN_DB)
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'fairchore_test'")
    if not cur.fetchone():
        cur.execute("CREATE DATABASE fairchore_test")
    cur.close()
    admin.close()

    conn = psycopg2.connect(_TEST_DB)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(_SCHEMA_DDL)
    cur.close()
    conn.close()

    yield

    # Drop test DB after the whole session
    admin = psycopg2.connect(_POSTGRES_ADMIN_DB)
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'fairchore_test'")
    cur.execute("DROP DATABASE IF EXISTS fairchore_test")
    cur.close()
    admin.close()


# ── Function-scoped: clean slate before every single test ────────────────────

@pytest.fixture(autouse=True)
def clean_tables():
    conn = psycopg2.connect(_TEST_DB)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        TRUNCATE allocation_results, assignment_history, burden_scores, chores,
                 household_members, households, users
        RESTART IDENTITY CASCADE
    """)
    cur.close()
    conn.close()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def db():
    """Raw psycopg2 connection to the test database for DB-level assertions."""
    conn = psycopg2.connect(_TEST_DB)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def prod_db():
    """Read-only connection to the production DB for seed data verification."""
    conn = psycopg2.connect(_PROD_DB)
    conn.autocommit = True
    yield conn
    conn.close()


# ── Helper functions available to all tests ───────────────────────────────────

def register(client, username="Alice", email="alice@test.com", password="password123"):
    res = client.post("/api/register", json={"name": username, "email": email, "password": password})
    return res


def login(client, email="alice@test.com", password="password123"):
    res = client.post("/api/login", json={"email": email, "password": password})
    return res


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_token(client, email="alice@test.com", password="password123"):
    res = login(client, email, password)
    return json.loads(res.data)["token"]


def create_household(client, token, name="Test House"):
    return client.post("/api/households", json={"name": name},
                       headers=auth_headers(token))


def add_chore(client, token, household_id, title="Dishes"):
    return client.post(f"/api/households/{household_id}/chores",
                       json={"title": title},
                       headers=auth_headers(token))


def save_preferences(client, token, household_id, ratings):
    return client.post(f"/api/households/{household_id}/preferences",
                       json={"ratings": ratings},
                       headers=auth_headers(token))


def run_allocation(client, token, household_id, algorithm="round-robin"):
    return client.post(f"/api/households/{household_id}/allocate",
                       json={"algorithm": algorithm},
                       headers=auth_headers(token))
