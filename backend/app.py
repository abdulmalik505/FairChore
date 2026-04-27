"""
FairChore Backend API — v5.0 "Fair Always" with Temporal Reciprocity
"""

import sys
import os
import re
import json
import hmac
import hashlib
import base64
import secrets
import string
import traceback
from datetime import datetime, timedelta, timezone, date
from functools import wraps

# Add project root so we can import from algorithms/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify, g, send_from_directory
from flask_cors import CORS

from algorithms import (
    greedy_round_robin as round_robin,
    bag_filling,
    top_trading_envy_cycle,
    compute_all_metrics,
)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

from dotenv import load_dotenv
load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

if not SECRET_KEY or not DATABASE_URL:
    missing = [k for k, v in {"SECRET_KEY": SECRET_KEY, "DATABASE_URL": DATABASE_URL}.items() if not v]
    print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
    print("Copy .env.example to .env and fill in your values.")
    sys.exit(1)

LAMBDA = 0.3  # History weighting factor

# Rating weights for normalization (1=Fine, 2=Neutral, 3=Don't like, 4=Strongly dislike)
RATING_COSTS = {1: 3, 2: 4, 3: 5, 4: 6}

_ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app = Flask(__name__, static_folder=None)
CORS(app, origins=_ALLOWED_ORIGINS)


# ─── JSON SAFETY ─────────────────────────────────────────────────────────────
# Python's default json emits Infinity/-Infinity/NaN for floats, which is NOT
# valid JSON and crashes browser JSON.parse. Override Flask's JSON provider
# so any non-finite float silently becomes null on the wire.

import math
from flask.json.provider import DefaultJSONProvider

def _sanitize_for_json(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj

class _SafeJSONProvider(DefaultJSONProvider):
    def dumps(self, obj, **kwargs):
        return super().dumps(_sanitize_for_json(obj), **kwargs)

app.json = _SafeJSONProvider(app)


# ─── DATABASE ────────────────────────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


# ─── JWT AUTH ────────────────────────────────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)


def jwt_encode(payload: dict) -> str:
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload).encode())
    sig_input = f"{header}.{body}".encode()
    sig = hmac.new(SECRET_KEY.encode(), sig_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(sig)}"


def jwt_decode(token: str) -> dict:
    parts = token.split('.')
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    header, body, sig = parts
    sig_input = f"{header}.{body}".encode()
    expected_sig = hmac.new(SECRET_KEY.encode(), sig_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid token signature")
    payload = json.loads(_b64url_decode(body))
    if payload.get('exp', 0) < datetime.now(timezone.utc).timestamp():
        raise ValueError("Token expired")
    return payload


def make_token(user_id: int, username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt_encode({"sub": user_id, "username": username, "exp": int(exp.timestamp())})


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth[7:]
        try:
            payload = jwt_decode(token)
            g.user_id = payload['sub']
            g.username = payload['username']
        except ValueError as e:
            return jsonify({"error": str(e)}), 401
        return f(*args, **kwargs)
    return decorated


# ─── PASSWORD HASHING ────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000)
    return f"{salt}:{h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(':', 1)
        expected = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000).hex()
        return hmac.compare_digest(expected, h)
    except Exception:
        return False


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def generate_join_code(conn) -> str:
    alphabet = string.ascii_uppercase + string.digits
    cur = conn.cursor()
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        cur.execute("SELECT 1 FROM households WHERE join_code = %s", (code,))
        if not cur.fetchone():
            return code


def is_member(conn, household_id: int, user_id: int) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM household_members WHERE household_id = %s AND user_id = %s",
        (household_id, user_id)
    )
    return cur.fetchone() is not None


def is_admin(conn, household_id: int, user_id: int) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM households WHERE id = %s AND admin_id = %s",
        (household_id, user_id)
    )
    return cur.fetchone() is not None


# ─── HISTORICAL LOAD ────────────────────────────────────────────────────────

def compute_historical_burdens(cur, house_id, member_ids):
    """
    Compute time-weighted HistoricalBurden for each member.
    HistoricalBurden = 0.5 × Weekly + 0.3 × Monthly + 0.2 × Daily
    Each component is sum of burden_at_time for assignments in that period.
    Normalized to 0–5 scale (ratio to household average × 2.5) so it stays
    comparable to the 1–5 preference range.
    """
    today = date.today()
    daily_start = today
    weekly_start = today - timedelta(days=7)
    monthly_start = today - timedelta(days=30)

    loads = {}
    for uid in member_ids:
        cur.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN ah.date_assigned >= %s THEN ah.burden_at_time ELSE 0 END), 0) AS daily,
                COALESCE(SUM(CASE WHEN ah.date_assigned >= %s THEN ah.burden_at_time ELSE 0 END), 0) AS weekly,
                COALESCE(SUM(CASE WHEN ah.date_assigned >= %s THEN ah.burden_at_time ELSE 0 END), 0) AS monthly
            FROM assignment_history ah
            JOIN chores c ON c.id = ah.chore_id
            WHERE ah.user_id = %s AND c.household_id = %s
        """, (daily_start, weekly_start, monthly_start, uid, house_id))
        row = cur.fetchone()
        daily = float(row['daily'] if isinstance(row, dict) else row[0])
        weekly = float(row['weekly'] if isinstance(row, dict) else row[1])
        monthly = float(row['monthly'] if isinstance(row, dict) else row[2])
        raw = 0.2 * daily + 0.5 * weekly + 0.3 * monthly
        loads[uid] = raw

    # Normalize to 0–5 scale: ratio to household average × 2.5
    values = list(loads.values())
    avg = sum(values) / len(values) if values else 1
    if avg == 0:
        avg = 1  # Avoid division by zero

    normalized = {}
    for uid, raw in loads.items():
        ratio = raw / avg  # 1.0 = fair share
        normalized[uid] = round(ratio * 2.5, 2)  # Center at 2.5, range roughly 0–5

    return normalized


def compute_burden_balance(cur, house_id, member_ids):
    """Compute cumulative per-household burden sums for the balance bar.

    Returns lifetime totals (no time window) so the displayed bar and the
    algorithm's picking order share one source of truth: the sum of
    burden_at_time for every confirmed assignment in this household.
    """
    burdens = {}
    for uid in member_ids:
        cur.execute("""
            SELECT COALESCE(SUM(ah.burden_at_time), 0) AS total_burden
            FROM assignment_history ah
            JOIN chores c ON c.id = ah.chore_id
            WHERE ah.user_id = %s AND c.household_id = %s
        """, (uid, house_id))
        row = cur.fetchone()
        val = row['total_burden'] if isinstance(row, dict) else row[0]
        burdens[uid] = float(val) if val is not None else 0.0

    total = sum(burdens.values())
    n = len(member_ids)
    avg = total / n if n > 0 else 1
    if avg == 0:
        avg = 1

    return burdens, avg


# ─── AUTH ENDPOINTS ──────────────────────────────────────────────────────────

@app.route('/api/register', methods=['POST'])
def register():
    """
    POST /api/register — Create a new user account.
    Body: { name, email, password (min 6 chars) }
    Returns: { token (JWT), user: { id, name, email } }
    Errors: 400 missing/invalid fields, 409 email already taken
    """
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not name or not email or not password:
        return jsonify({"error": "name, email, and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({"error": "Invalid email address"}), 400

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return jsonify({"error": "Email already registered"}), 409

        pw_hash = hash_password(password)
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING id, username, email",
            (name, email, pw_hash)
        )
        user = dict(cur.fetchone())
        conn.commit()

        token = make_token(user['id'], user['username'])
        return jsonify({"token": token, "user": {"id": user['id'], "name": user['username'], "email": user['email']}}), 201
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/login', methods=['POST'])
def login():
    """
    POST /api/login — Authenticate an existing user.
    Body: { email, password }
    Returns: { token (JWT, 7-day expiry), user: { id, name, email } }
    Errors: 400 missing fields, 401 wrong credentials
    """
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, username, email, password_hash FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        if not user or not user['password_hash'] or not verify_password(password, user['password_hash']):
            return jsonify({"error": "Invalid email or password"}), 401

        token = make_token(user['id'], user['username'])
        return jsonify({"token": token, "user": {"id": user['id'], "name": user['username'], "email": user['email']}})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/me', methods=['GET'])
@require_auth
def me():
    """
    GET /api/me — Return the currently authenticated user's profile.
    Auth: Bearer token required.
    Returns: { id, name, email }
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, username, email FROM users WHERE id = %s", (g.user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"id": user['id'], "name": user['username'], "email": user['email']})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── HOUSEHOLD ENDPOINTS ─────────────────────────────────────────────────────

@app.route('/api/households', methods=['GET'])
@require_auth
def list_households():
    """
    GET /api/households — List all households the current user belongs to.
    Auth: Bearer token required.
    Returns: [ { id, name, join_code, admin_id, member_count } ]
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT h.id, h.name, h.join_code, h.admin_id,
                   (SELECT COUNT(*) FROM household_members hm2 WHERE hm2.household_id = h.id) AS member_count
            FROM households h
            JOIN household_members hm ON hm.household_id = h.id AND hm.user_id = %s
            ORDER BY h.id
        """, (g.user_id,))
        rows = cur.fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/households', methods=['POST'])
@require_auth
def create_household():
    """
    POST /api/households — Create a new household. Creator becomes admin.
    Auth: Bearer token required.
    Body: { name }
    Returns: { id, name, join_code (6-char), admin_id }
    """
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        code = generate_join_code(conn)
        cur.execute(
            "INSERT INTO households (name, join_code, admin_id) VALUES (%s, %s, %s) RETURNING id, name, join_code, admin_id",
            (name, code, g.user_id)
        )
        h = dict(cur.fetchone())
        cur.execute("INSERT INTO household_members (household_id, user_id) VALUES (%s, %s)", (h['id'], g.user_id))
        conn.commit()
        return jsonify(h), 201
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/households/join', methods=['POST'])
@require_auth
def join_household():
    """
    POST /api/households/join — Join a household using its 6-character join code.
    Auth: Bearer token required.
    Body: { code }
    Side effect: New member's total_burden is set to the household average
                 so they don't unfairly dominate turn order on first allocation.
    Returns: { id, name }
    Errors: 404 invalid code, 409 already a member
    """
    data = request.get_json() or {}
    code = (data.get('code') or '').strip().upper()
    if not code:
        return jsonify({"error": "code is required"}), 400

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name FROM households WHERE UPPER(join_code) = %s", (code,))
        h = cur.fetchone()
        if not h:
            return jsonify({"error": "Household not found"}), 404

        if is_member(conn, h['id'], g.user_id):
            return jsonify({"error": "Already a member of this household"}), 409

        cur.execute("INSERT INTO household_members (household_id, user_id) VALUES (%s, %s)", (h['id'], g.user_id))

        # New Member Neutrality: initialize their total_burden to household average
        cur.execute("""
            SELECT COALESCE(AVG(u.total_burden_accumulated), 0) AS avg_burden
            FROM users u
            JOIN household_members hm ON hm.user_id = u.id
            WHERE hm.household_id = %s
        """, (h['id'],))
        avg = float(cur.fetchone()['avg_burden'])
        if avg > 0:
            cur.execute("UPDATE users SET total_burden_accumulated = %s WHERE id = %s", (avg, g.user_id))

        conn.commit()
        return jsonify({"id": h['id'], "name": h['name']})
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/households/<int:house_id>', methods=['GET'])
@require_auth
def get_household(house_id):
    """
    GET /api/households/<id> — Full household details for a member.
    Auth: Bearer token required. User must be a member of this household.
    Returns: { id, name, join_code, admin_id, members[], chores[] }
             Each chore includes per-user capability flags.
    Errors: 403 not a member, 404 not found
    """
    conn = get_db()
    try:
        if not is_member(conn, house_id, g.user_id):
            return jsonify({"error": "Not a member of this household"}), 403

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, join_code, admin_id FROM households WHERE id = %s", (house_id,))
        h = cur.fetchone()
        if not h:
            return jsonify({"error": "Household not found"}), 404

        # Members
        cur.execute("""
            SELECT u.id, u.username AS name, u.email, u.total_burden_accumulated AS total_burden
            FROM users u
            JOIN household_members hm ON hm.user_id = u.id
            WHERE hm.household_id = %s
            ORDER BY u.id
        """, (house_id,))
        members = [dict(r) for r in cur.fetchall()]
        for m in members:
            m['total_burden'] = float(m['total_burden']) if m.get('total_burden') is not None else 0.0

        # All chores (active + inactive) with capabilities per user
        cur.execute(
            "SELECT id, title, COALESCE(description, '') AS description, is_active FROM chores WHERE household_id = %s ORDER BY is_active DESC, id",
            (house_id,)
        )
        chore_rows = cur.fetchall()

        chores = []
        for c in chore_rows:
            cur.execute(
                "SELECT user_id, is_capable FROM burden_scores WHERE chore_id = %s",
                (c['id'],)
            )
            caps = {str(row['user_id']): row['is_capable'] for row in cur.fetchall()}
            chores.append({"id": c['id'], "title": c['title'], "description": c['description'], "is_active": bool(c['is_active']), "capabilities": caps})

        result = dict(h)
        result['members'] = members
        result['chores'] = chores
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── EFFORT BALANCE ENDPOINT ────────────────────────────────────────────────

@app.route('/api/households/<int:house_id>/burden-balance', methods=['GET'])
@require_auth
def burden_balance(house_id):
    """
    GET /api/households/<id>/burden-balance — Lifetime workload balance.
    Auth: Bearer token required. User must be a member.

    Returns: { members: [ { member_id, name, burden, percentage } ] }
             percentage is burden / fair-share × 100 (100% = perfectly equal).
             For backwards compatibility the same array is also exposed under
             the legacy `daily`, `weekly`, and `monthly` keys.
    Used by the HomeScreen burden-balance bar chart.
    """
    conn = get_db()
    try:
        if not is_member(conn, house_id, g.user_id):
            return jsonify({"error": "Not a member of this household"}), 403

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.id, u.username AS name
            FROM users u
            JOIN household_members hm ON hm.user_id = u.id
            WHERE hm.household_id = %s
            ORDER BY u.id
        """, (house_id,))
        members = cur.fetchall()
        member_ids = [m['id'] for m in members]
        name_map = {m['id']: m['name'] for m in members}

        burdens, avg = compute_burden_balance(cur, house_id, member_ids)
        rows = []
        for uid in member_ids:
            pct = round(burdens[uid] / avg * 100, 1) if avg > 0 else 100.0
            rows.append({
                "member_id": uid,
                "name": name_map[uid],
                "burden": float(burdens[uid]),
                "percentage": pct,
            })

        return jsonify({
            "members": rows,
            "daily":   rows,
            "weekly":  rows,
            "monthly": rows,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── CHORE ENDPOINTS ─────────────────────────────────────────────────────────

@app.route('/api/households/<int:house_id>/chores', methods=['POST'])
@require_auth
def add_chore(house_id):
    """
    POST /api/households/<id>/chores — Add a new chore to the household.
    Auth: Bearer token required. Any household member.

    Body: { title, description? (optional), capabilities?: { user_id: bool } }

    Preference inheritance: if any other chore in the same household has the
    same title (case-insensitive) — active, inactive, or already in history —
    the new chore inherits its scores/capabilities from the most recent match.
    This lets a member re-add "Vacuuming" or any seed-library chore by name
    and have it allocatable immediately, without anyone re-rating.

    The `capabilities` body field, if provided, overrides any inherited
    capability for the listed users. `my_rating` (1–4), if provided, overrides
    the requesting user's inherited score.

    Returns: { id, title, description, capabilities, inherited_from? }
    Errors: 400 missing title, 403 not a member
    """
    conn = get_db()
    try:
        # Any household member can add a chore. Allocations remain admin-only,
        # so even though anyone can grow the pool, only the admin decides
        # when an allocation actually runs.
        if not is_member(conn, house_id, g.user_id):
            return jsonify({"error": "Not a member of this household"}), 403

        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({"error": "title is required"}), 400
        capabilities = data.get('capabilities', {})

        description = (data.get('description') or '').strip()
        my_rating = data.get('my_rating', None)

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Add description column if it doesn't exist (migration-safe)
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name='chores' AND column_name='description'
        """)
        if not cur.fetchone():
            cur.execute("ALTER TABLE chores ADD COLUMN description TEXT DEFAULT ''")

        cur.execute(
            "INSERT INTO chores (household_id, title, description) VALUES (%s, %s, %s) RETURNING id, title, description",
            (house_id, title, description)
        )
        chore = dict(cur.fetchone())

        # Look up the most recent matching chore in this household (any state)
        # whose title equals the new one (case-insensitive). If found, that
        # chore acts as a template — its scores and capabilities are copied
        # into the new chore for every CURRENT member.
        cur.execute("""
            SELECT id FROM chores
            WHERE household_id = %s AND LOWER(title) = LOWER(%s) AND id <> %s
            ORDER BY id DESC LIMIT 1
        """, (house_id, title, chore['id']))
        template_row = cur.fetchone()
        template_id = template_row['id'] if template_row else None

        cur.execute(
            "SELECT user_id FROM household_members WHERE household_id = %s",
            (house_id,)
        )
        member_ids = [r['user_id'] for r in cur.fetchall()]

        if template_id is not None:
            # Pull every score/capability the template has, keyed by user_id
            cur.execute(
                "SELECT user_id, score, is_capable FROM burden_scores WHERE chore_id = %s",
                (template_id,)
            )
            tmpl = {r['user_id']: r for r in cur.fetchall()}
        else:
            tmpl = {}

        applied_caps = {}
        for uid in member_ids:
            inherited = tmpl.get(uid)
            # The requesting admin always starts unrated for chores they add —
            # they must rate it themselves via the Preferences screen. This is
            # deliberate: inheritance is for OTHER members so allocations can
            # still run, while the admin participates fairly like everyone else.
            if uid == g.user_id:
                score = 0
            else:
                score = inherited['score'] if inherited else 0
            inherited_cap = inherited['is_capable'] if inherited else True
            # request body capabilities override the inherited value if present
            is_capable = capabilities.get(str(uid), inherited_cap)
            applied_caps[str(uid)] = is_capable
            cur.execute(
                "INSERT INTO burden_scores (user_id, chore_id, score, is_capable) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (user_id, chore_id) DO UPDATE "
                "  SET score = EXCLUDED.score, is_capable = EXCLUDED.is_capable",
                (uid, chore['id'], score, is_capable)
            )

        # If the creator set a personal preference rating (1-4), store it as a score
        if my_rating and int(my_rating) in RATING_COSTS:
            rating_cost = RATING_COSTS[int(my_rating)]
            cur.execute(
                "UPDATE burden_scores SET score = %s WHERE user_id = %s AND chore_id = %s",
                (rating_cost, g.user_id, chore['id'])
            )

        conn.commit()
        chore['capabilities'] = applied_caps
        if template_id is not None:
            chore['inherited_from'] = template_id
        return jsonify(chore), 201
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/households/<int:house_id>/chore-titles', methods=['GET'])
@require_auth
def list_chore_titles(house_id):
    """
    GET /api/households/<id>/chore-titles — Distinct chore titles ever used in
    this household (case-insensitive dedup, picking the most recently created
    chore for each canonical title).

    Drives the Add Chore autocomplete: typing a title that matches one of
    these will inherit scores + capabilities from the underlying chore.

    Returns: [ { title, last_chore_id, last_state }, ... ]
             last_state ∈ {"active", "inactive", "completed", "assigned"}
             — purely informational for the UI.
    Errors: 403 not a member
    """
    conn = get_db()
    try:
        if not is_member(conn, house_id, g.user_id):
            return jsonify({"error": "Not a member of this household"}), 403

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # DISTINCT ON (LOWER(title)) keeps the newest chore (highest id) per
        # canonical title, preserving its original casing for display.
        cur.execute("""
            SELECT DISTINCT ON (LOWER(c.title))
                   c.id, c.title, c.is_active,
                   EXISTS (SELECT 1 FROM assignment_history ah WHERE ah.chore_id = c.id) AS in_history,
                   EXISTS (SELECT 1 FROM assignment_history ah WHERE ah.chore_id = c.id
                           AND ah.completed_at IS NULL) AS open_assignment
            FROM chores c
            WHERE c.household_id = %s
            ORDER BY LOWER(c.title), c.id DESC
        """, (house_id,))
        rows = cur.fetchall()

        out = []
        for r in rows:
            if not r['is_active'] and not r['in_history']:
                state = 'inactive'  # in the seed library
            elif r['open_assignment']:
                state = 'assigned'  # currently owed by someone
            elif r['in_history']:
                state = 'completed'  # everyone marked it done
            else:
                state = 'active'  # active but never allocated yet
            out.append({
                'title': r['title'],
                'last_chore_id': r['id'],
                'last_state': state,
            })
        # Newest-canonical-id first so frequently-used names rise to the top
        out.sort(key=lambda x: -x['last_chore_id'])
        return jsonify(out)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/chores/<int:chore_id>', methods=['DELETE'])
@require_auth
def delete_chore(chore_id):
    """
    DELETE /api/chores/<id> — Soft-delete a chore (sets is_active=FALSE).
    Auth: Bearer token required. Admin only.
    The chore is not physically removed — soft deletion preserves assignment history.
    Inactive chores are excluded from future allocations.
    Returns: { success: true }
    Errors: 403 not admin, 404 chore not found
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT household_id FROM chores WHERE id = %s", (chore_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Chore not found"}), 404
        if not is_admin(conn, row['household_id'], g.user_id):
            return jsonify({"error": "Only the household admin can delete chores"}), 403

        cur.execute("UPDATE chores SET is_active = FALSE WHERE id = %s", (chore_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/chores/<int:chore_id>/activate', methods=['PATCH'])
@require_auth
def activate_chore(chore_id):
    """
    PATCH /api/chores/<id>/activate — Reactivate a soft-deleted chore (sets is_active=TRUE).
    Auth: Bearer token required. Admin only.
    Returns: { success: true }
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT household_id FROM chores WHERE id = %s", (chore_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Chore not found"}), 404
        if not is_admin(conn, row['household_id'], g.user_id):
            return jsonify({"error": "Only the household admin can activate chores"}), 403
        cur.execute("UPDATE chores SET is_active = TRUE WHERE id = %s", (chore_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── ASSIGNMENT COMPLETION ──────────────────────────────────────────────────

@app.route('/api/assignments/<int:assignment_id>/complete', methods=['POST', 'DELETE'])
@require_auth
def toggle_assignment_complete(assignment_id):
    """
    POST   /api/assignments/<id>/complete — Mark a chore as done (sets completed_at).
    DELETE /api/assignments/<id>/complete — Undo completion (clears completed_at).
    Auth: Bearer token required. Only the assignee can change their own state.
    Other household members can view completed_at via the history endpoint (read-only).
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT user_id FROM assignment_history WHERE id = %s", (assignment_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Assignment not found"}), 404
        if row['user_id'] != g.user_id:
            return jsonify({"error": "You can only update your own assignments"}), 403

        if request.method == 'POST':
            cur.execute(
                "UPDATE assignment_history SET completed_at = NOW() WHERE id = %s",
                (assignment_id,)
            )
        else:  # DELETE = undo completion
            cur.execute(
                "UPDATE assignment_history SET completed_at = NULL WHERE id = %s",
                (assignment_id,)
            )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── PREFERENCES ENDPOINTS ───────────────────────────────────────────────────

@app.route('/api/households/<int:house_id>/preferences', methods=['POST'])
@require_auth
def submit_preferences(house_id):
    """
    POST /api/households/<id>/preferences — Submit chore preference ratings.
    Auth: Bearer token required. Any household member.
    Body: { ratings: { chore_id: 1-4 } }
          Rating scale: 1=Fine, 2=Neutral, 3=Don't like, 4=Strongly dislike
    Normalisation: ratings are converted to weights via RATING_COSTS, then
                   scaled so each member's scores sum to exactly 100.
                   This 100-point budget prevents strategic gaming.
    Returns: { success: true, scores: { chore_id: normalised_score } }
    Errors: 403 not a member
    """
    conn = get_db()
    try:
        if not is_member(conn, house_id, g.user_id):
            return jsonify({"error": "Not a member of this household"}), 403

        data = request.get_json() or {}
        ratings = data.get('ratings', {})
        scores_raw = data.get('scores', {})

        if ratings:
            m = len(ratings)

            if m >= 3:
                # Tier 1 — cap on 😤 only (value=4)
                max_top = max(1, m // 3)
                top_count = sum(1 for r in ratings.values() if int(r) == 4)
                if top_count > max_top:
                    return jsonify({
                        "error": f"Too many \U0001f624 ratings. Max {max_top} allowed."
                    }), 400

                # Tier 2 — cap on 😕 + 😤 combined (values 3 and 4)
                max_upper = max(2, (m * 2) // 3)
                upper_count = sum(1 for r in ratings.values() if int(r) >= 3)
                if upper_count > max_upper:
                    return jsonify({
                        "error": f"Too many high ratings. At least {m - max_upper} chores must be rated \U0001f642 or \U0001f610."
                    }), 400

            # Normalize using weights as proportional scores
            costs = {cid: RATING_COSTS.get(int(v), 4) for cid, v in ratings.items()}
            cost_sum = sum(costs.values())
            if cost_sum == 0:
                cost_sum = 1
            scores = {}
            for chore_id_str, cost in costs.items():
                scores[chore_id_str] = max(1, round(cost * 100 / cost_sum))

            # Fix rounding to ensure sum = 100
            total = sum(scores.values())
            diff = 100 - total
            if diff != 0 and scores:
                best_key = max(scores, key=scores.get)
                scores[best_key] = max(1, scores[best_key] + diff)

        elif scores_raw:
            # Legacy path: accept pre-normalized 100-sum scores
            scores = {str(k): int(v) for k, v in scores_raw.items()}
            total = sum(scores.values())
            if abs(total - 100) > 2:
                return jsonify({"error": f"Scores must sum to 100 (got {total})"}), 400
        else:
            return jsonify({"error": "ratings or scores required"}), 400

        cur = conn.cursor()
        for chore_id_str, score_val in scores.items():
            chore_id = int(chore_id_str)
            cur.execute("""
                INSERT INTO burden_scores (user_id, chore_id, score)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, chore_id) DO UPDATE SET score = EXCLUDED.score
            """, (g.user_id, chore_id, int(score_val)))

        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/households/<int:house_id>/my-preferences', methods=['GET'])
@require_auth
def get_my_preferences(house_id):
    """
    GET /api/households/<id>/my-preferences — Retrieve stored preference scores.
    Auth: Bearer token required. Any household member.
    Returns: { chore_id: { score, is_capable } }
             score=0 means this chore has not been rated yet.
    Used by the frontend to pre-populate the Preferences screen on revisit.
    """
    conn = get_db()
    try:
        if not is_member(conn, house_id, g.user_id):
            return jsonify({"error": "Not a member of this household"}), 403

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT es.chore_id, es.score, es.is_capable
            FROM burden_scores es
            JOIN chores c ON c.id = es.chore_id
            WHERE es.user_id = %s AND c.household_id = %s AND c.is_active = TRUE
        """, (g.user_id, house_id))
        result = {str(r['chore_id']): {"score": r['score'], "is_capable": r['is_capable']} for r in cur.fetchall()}
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/households/<int:house_id>/preferences-ready', methods=['GET'])
@require_auth
def preferences_ready(house_id):
    """
    GET /api/households/<id>/preferences-ready — Check which members have rated all chores.
    Auth: Bearer token required. Any household member.
    A member is "ready" when: all chore scores > 0 AND scores sum to 100 ± 2.
    Returns: [ { id, name, ready: bool } ] for each member.
    Used by the Allocate screen to block allocation until all members are ready.
    """
    conn = get_db()
    try:
        if not is_member(conn, house_id, g.user_id):
            return jsonify({"error": "Not a member of this household"}), 403

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.id, u.username AS name
            FROM users u
            JOIN household_members hm ON hm.user_id = u.id
            WHERE hm.household_id = %s
        """, (house_id,))
        members = cur.fetchall()

        result = []
        for m in members:
            # Ready = has rated every UNALLOCATED active chore (score > 0).
            # A chore that has ever been allocated (in assignment_history) is
            # excluded from future allocations and so does not need re-rating.
            cur.execute("""
                SELECT
                    COUNT(*) AS unassigned_total,
                    COUNT(*) FILTER (WHERE COALESCE(es.score, 0) = 0) AS unrated
                FROM chores c
                LEFT JOIN burden_scores es ON es.chore_id = c.id AND es.user_id = %s
                WHERE c.household_id = %s AND c.is_active = TRUE
                  AND c.id NOT IN (SELECT chore_id FROM assignment_history)
            """, (m['id'], house_id))
            row = cur.fetchone()
            unassigned_total = row['unassigned_total']
            unrated = row['unrated']
            # Ready if there are unassigned chores and all are rated,
            # OR there are no unassigned chores (nothing to allocate yet).
            ready = (unassigned_total == 0) or (unrated == 0)
            result.append({"id": m['id'], "name": m['name'], "ready": ready,
                           "unassigned_total": unassigned_total, "unrated": unrated})
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── ALLOCATION ENGINE ──────────────────────────────────────────────────────

EXPLANATIONS = {
    'round-robin': "Round-Robin: members took turns picking their least-hated chore, ordered by lowest historical load. Guarantees EF1 (no one envies another by more than one chore) for unconstrained preferences. Capability constraints may introduce unavoidable envy in some cases.",
    'bag-filling-practical': "Bag-Filling: chores were bundled to minimize variance of AdjustedScore across the household. This gives the best workload balance.",
    'top-trading': "Top-Trading: bundles are swapped along envy cycles, weighted by historical credits, until everyone is assigned fairly. Guarantees EF1 for unconstrained preferences. Capability constraints may introduce unavoidable envy in some cases.",
}


def _run_algorithm(algorithm_name, scores, chores, feasible=None):
    if algorithm_name == 'round-robin':
        return round_robin(scores, feasible)
    elif algorithm_name == 'bag-filling-paper':
        return bag_filling(scores, feasible, variant='paper')
    elif algorithm_name == 'bag-filling-practical':
        return bag_filling(scores, feasible, variant='practical')
    elif algorithm_name == 'top-trading':
        return top_trading_envy_cycle(scores, feasible)
    else:
        raise ValueError(f"Unknown algorithm: {algorithm_name}")


@app.route('/api/households/<int:house_id>/allocate', methods=['POST'])
@require_auth
def allocate(house_id):
    """
    POST /api/households/<id>/allocate — Run a fair-division allocation algorithm.
    Auth: Bearer token required. Admin only.
    Body: { algorithm: 'round-robin' | 'bag-filling-practical' | 'bag-filling-paper' | 'top-trading' }
    Process:
      1. Fetch members ordered by total_burden_accumulated ASC (least-burdened picks first)
      2. Build AdjustedScore = preference + λ × HistoricalLoad (temporal reciprocity)
      3. Run selected algorithm on adjusted scores with capability constraints
      4. Save each assignment to assignment_history; update users.total_burden_accumulated
      5. Compute fairness metrics (EF1, MMS ratio, workload balance) on ORIGINAL scores
    Returns: { algorithm, allocation[], metrics{}, explanation }
    Errors: 403 not admin, 404 no members/chores
    """
    conn = get_db()
    try:
        if not is_admin(conn, house_id, g.user_id):
            return jsonify({"error": "Only the household admin can run allocations"}), 403

        data = request.get_json() or {}
        algorithm_name = data.get('algorithm', 'bag-filling-practical')
        # Optional: allocate specific chore IDs (atomic allocation)
        chore_ids = data.get('chore_ids', None)  # None = all active

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Fetch members ordered by total_burden_accumulated ASC
        cur.execute("""
            SELECT u.id, u.username, u.total_burden_accumulated
            FROM users u
            JOIN household_members hm ON hm.user_id = u.id
            WHERE hm.household_id = %s
            ORDER BY u.total_burden_accumulated ASC
        """, (house_id,))
        members = cur.fetchall()

        # 2. Pool = active chores that have NEVER been allocated.
        # A chore is allocated exactly once: once it lands in assignment_history
        # (completed or not) it is "spoken for" and never re-enters the pool.
        # To "redo" something, the admin creates a new chore with the same name.
        if chore_ids and len(chore_ids) > 0:
            placeholders = ','.join(['%s'] * len(chore_ids))
            cur.execute(
                f"SELECT id, title FROM chores WHERE household_id = %s AND is_active = TRUE "
                f"AND id IN ({placeholders}) "
                f"AND id NOT IN (SELECT chore_id FROM assignment_history)",
                [house_id] + chore_ids
            )
        else:
            cur.execute("""
                SELECT c.id, c.title FROM chores c
                WHERE c.household_id = %s AND c.is_active = TRUE
                  AND c.id NOT IN (SELECT chore_id FROM assignment_history)
                ORDER BY c.id
            """, (house_id,))
        chore_rows = cur.fetchall()

        if not members:
            return jsonify({"error": "No members found"}), 404
        if not chore_rows:
            return jsonify({
                "error": "No new chores to allocate. Add a chore first, or activate one of the suggested chores from the Manage screen."
            }), 400

        chore_titles = [c['title'] for c in chore_rows]
        num_chores = len(chore_titles)
        default_score = 100 // num_chores if num_chores > 0 else 10
        member_ids = [m['id'] for m in members]

        # 3. Compute HistoricalLoad for AdjustedScore
        hist_loads = compute_historical_burdens(cur, house_id, member_ids)

        # 4. Build scores, feasible, and AdjustedScores
        scores = {}
        adjusted_scores = {}
        feasible = {}
        member_id_map = {}

        for m in members:
            name = m['username']
            member_id_map[name] = m['id']
            scores[name] = {}
            adjusted_scores[name] = {}
            feasible[name] = []

            cur.execute("""
                SELECT c.title, es.score, es.is_capable
                FROM burden_scores es
                JOIN chores c ON c.id = es.chore_id
                WHERE es.user_id = %s AND c.household_id = %s AND c.is_active = TRUE
            """, (m['id'], house_id))
            pref_rows = {r['title']: r for r in cur.fetchall()}

            hist = hist_loads.get(m['id'], 2.5)

            for title in chore_titles:
                if title in pref_rows:
                    raw_score = pref_rows[title]['score']
                    scores[name][title] = raw_score
                    if pref_rows[title]['is_capable']:
                        feasible[name].append(title)
                else:
                    raw_score = default_score
                    scores[name][title] = raw_score
                    feasible[name].append(title)

                # AdjustedScore = Preference + λ × HistoricalLoad
                # Preference is normalized 0-100 score; scale to 1-5 for formula
                pref_on_5 = max(1, min(5, raw_score / (100 / num_chores) * 2.5)) if num_chores > 0 else 3
                adjusted_scores[name][title] = round(pref_on_5 + LAMBDA * hist, 2)

            if not feasible[name]:
                feasible[name] = chore_titles[:]

        # 4b. Enforce: every member must have rated every active chore (score > 0).
        # Unrated chores (score=0 in burden_scores) mean the algorithm would use
        # an arbitrary default, producing unfair or meaningless results.
        unrated = []
        for name, chore_scores in scores.items():
            for title, s in chore_scores.items():
                if s == 0:
                    unrated.append(f"{name} — {title}")
        if unrated:
            sample = unrated[:3]
            extra = f" (and {len(unrated) - 3} more)" if len(unrated) > 3 else ""
            return jsonify({
                "error": (
                    f"Cannot allocate: {len(unrated)} chore rating(s) missing. "
                    f"{', '.join(sample)}{extra}. "
                    "All members must rate every chore before running an allocation."
                )
            }), 400

        # 5. Convert feasible → capable dict-of-dicts
        capable = {}
        for name, can_do in feasible.items():
            capable[name] = {title: (title in can_do) for title in chore_titles}

        # 6. Run algorithm.
        # Round-Robin and Top-Trading use adjusted_scores (preference + λ×history) so that
        # members who have done more work recently are treated as if they dislike all chores
        # slightly more — causing them to pick first (temporal reciprocity).
        # Bag-Filling's threshold formula was designed for 100-sum budget scores, NOT for the
        # 1–5 adjusted range. Running bag-filling on adjusted_scores (1–5) makes thresholds
        # too small (~4 per member), so bags hold only 1–2 chores, leaving the last member
        # with all remaining chores. Fix: bag-filling always uses raw 100-sum scores.
        if algorithm_name in ('bag-filling-paper', 'bag-filling-practical'):
            allocation = _run_algorithm(algorithm_name, scores, chore_titles, capable)
        else:
            allocation = _run_algorithm(algorithm_name, adjusted_scores, chore_titles, capable)

        # 6b. Post-process: fix zero-chore members.
        # Bag-Filling can leave some members with 0 chores when capability constraints
        # cause bags to be fully consumed by unconstrained members before constrained
        # members get a turn. Redistribute one chore at a time from a donor who would
        # still hold >=1 chore after the gift (prevents ping-ponging when there are
        # fewer chores than members).
        zero_members = [m for m, ch in allocation.items() if len(ch) == 0]
        while zero_members:
            moved = False
            for empty_m in zero_members:
                # Only donors with >=2 chores are eligible — giving from a 1-chore
                # donor would just re-create a zero elsewhere and loop forever.
                donor = max(
                    (m for m in allocation if m != empty_m and len(allocation[m]) >= 2),
                    key=lambda m: len(allocation[m]),
                    default=None
                )
                if donor is None:
                    break
                gift = next(
                    (c for c in allocation[donor] if capable[empty_m][c]),
                    None
                )
                if gift is None:
                    continue  # try next empty member; this donor has nothing transferable
                allocation[donor].remove(gift)
                allocation[empty_m].append(gift)
                moved = True
            if not moved:
                break
            zero_members = [m for m, ch in allocation.items() if len(ch) == 0]

        # 7. Compute metrics using original preference scores (not adjusted)
        metrics = compute_all_metrics(scores, allocation)

        # 8. Build response (DRY RUN — nothing saved to DB yet).
        # Each chore is returned with its database ID so the confirm endpoint
        # can save by ID (preventing confusion if two chores share a name).
        # burden_at_time is precomputed here (household average score) and sent
        # back so the confirm endpoint doesn't need to re-query.
        chore_id_map = {c['title']: c['id'] for c in chore_rows}
        result_members = []
        for m in members:
            name = m['username']
            assigned_titles = allocation.get(name, [])
            chore_objs = []
            for title in assigned_titles:
                cid = chore_id_map[title]
                cur.execute(
                    "SELECT ROUND(AVG(score)::numeric, 2) AS avg_score FROM burden_scores WHERE chore_id = %s AND score > 0",
                    (cid,)
                )
                avg_row = cur.fetchone()
                raw_avg = avg_row['avg_score'] if avg_row and avg_row['avg_score'] is not None else scores[name].get(title, 0)
                burden = float(raw_avg)
                chore_objs.append({"id": cid, "title": title, "burden_at_time": burden})

            # "burden" = sum of burden_at_time (household-average weights).
            # Matches the home burden-balance metric so percentages line up.
            burden_sum = sum(c['burden_at_time'] for c in chore_objs)
            # "perceived_burden" = this member's own preference sum (how heavy it
            # feels to THEM). Useful for personalised explanations.
            perceived = sum(scores[name].get(c['title'], 0) for c in chore_objs)
            result_members.append({
                "member": name,
                "member_id": m['id'],
                "chores": chore_objs,
                "burden": round(burden_sum, 2),
                "perceived_burden": perceived,
                "adjusted_burden": sum(adjusted_scores[name].get(c['title'], 0) for c in chore_objs),
                "past_burden": float(m['total_burden_accumulated'] or 0),
                "chore_count": len(chore_objs),
            })

        return jsonify({
            "algorithm": algorithm_name,
            "allocation": result_members,
            "metrics": metrics,
            "explanation": EXPLANATIONS.get(algorithm_name, ""),
            "scores": {name: {t: s for t, s in cscores.items()} for name, cscores in scores.items()},
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── CONFIRM ALLOCATION ──────────────────────────────────────────────────────

@app.route('/api/households/<int:house_id>/allocate/confirm', methods=['POST'])
@require_auth
def confirm_allocation(house_id):
    """
    POST /api/households/<id>/allocate/confirm — Persist a computed allocation.
    Auth: Bearer token required. Admin only.
    Body: { allocation: [ { member_id, chores: [{id, title, burden_at_time}], burden } ], algorithm }
    This is the second step of the two-phase allocation flow:
      1. POST /allocate  → computes, returns preview (nothing saved)
      2. POST /allocate/confirm → user approves → saves to assignment_history
    Using a shared confirmed_at timestamp for all rows in this batch lets the
    history endpoint identify each round uniquely, even on the same calendar day.
    """
    conn = get_db()
    try:
        if not is_admin(conn, house_id, g.user_id):
            return jsonify({"error": "Only the household admin can confirm allocations"}), 403

        data = request.get_json() or {}
        allocation = data.get('allocation', [])
        algorithm_name = data.get('algorithm', 'unknown')
        scores = data.get('scores', {})    # full scores matrix from dry-run
        metrics = data.get('metrics', {})  # ef1, mms etc. from dry-run

        if not allocation:
            return jsonify({"error": "allocation is required"}), 400

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Single timestamp shared by all inserts in this batch = one unique round
        confirmed_at = datetime.now(timezone.utc)

        for member_entry in allocation:
            uid = member_entry.get('member_id')
            chores = member_entry.get('chores', [])
            member_burden = 0.0

            for chore in chores:
                cid = chore.get('id')
                burden = float(chore.get('burden_at_time', 0) or 0)
                member_burden += burden
                cur.execute(
                    "INSERT INTO assignment_history "
                    "(user_id, chore_id, burden_at_time, algorithm_used, date_assigned, completed_at) "
                    "VALUES (%s, %s, %s, %s, %s, NULL)",
                    (uid, cid, burden, algorithm_name, confirmed_at)
                )

            cur.execute(
                "UPDATE users SET total_burden_accumulated = total_burden_accumulated + %s WHERE id = %s",
                (member_burden, uid)
            )

        # Save full scores matrix + metrics so past results can be replayed exactly.
        cur.execute("""
            INSERT INTO allocation_results (household_id, round_ts, algorithm, scores_json, metrics_json)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
            ON CONFLICT (round_ts) DO NOTHING
        """, (house_id, confirmed_at, algorithm_name,
              json.dumps(scores), json.dumps(metrics)))

        conn.commit()
        return jsonify({"success": True, "confirmed_at": confirmed_at.isoformat()})
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── HISTORY ENDPOINT ────────────────────────────────────────────────────────

@app.route('/api/households/<int:house_id>/history', methods=['GET'])
@require_auth
def get_history(house_id):
    """
    GET /api/households/<id>/history — All allocation rounds for this household.
    Auth: Bearer token required. Any household member.
    Returns: [ { round_ts, date_label, algorithm, assignments: [ { member, member_id, chores: [{id, title}] } ] } ]
    Rounds are identified by the shared confirmed_at timestamp (all rows in one
    confirmed allocation share the same timestamp). Returns up to 20 rounds.
    Chores are returned with IDs so the frontend can distinguish same-named chores.
    """
    conn = get_db()
    try:
        if not is_member(conn, house_id, g.user_id):
            return jsonify({"error": "Not a member of this household"}), 403

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT
                ah.id          AS assignment_id,
                ah.date_assigned,
                ah.algorithm_used,
                ah.completed_at,
                ah.user_id     AS member_id,
                u.username     AS member,
                c.id           AS chore_id,
                c.title        AS chore_title,
                COALESCE(c.description, '') AS chore_description
            FROM assignment_history ah
            JOIN users u ON u.id = ah.user_id
            JOIN chores c ON c.id = ah.chore_id
            WHERE c.household_id = %s
            ORDER BY ah.date_assigned DESC, ah.id DESC
            LIMIT 1000
        """, (house_id,))
        rows = cur.fetchall()

        # Group rows by the shared confirmation timestamp (= one round per batch).
        grouped = {}
        order = []
        for r in rows:
            ts = str(r['date_assigned'])
            if ts not in grouped:
                grouped[ts] = {
                    "round_ts": ts,
                    "date_label": str(r['date_assigned'])[:10],
                    "algorithm": r['algorithm_used'],
                    "assignments": {},
                }
                order.append(ts)
            mid = r['member_id']
            if mid not in grouped[ts]['assignments']:
                grouped[ts]['assignments'][mid] = {
                    "member": r['member'], "member_id": mid, "chores": []
                }
            grouped[ts]['assignments'][mid]['chores'].append({
                "id": r['chore_id'],
                "title": r['chore_title'],
                "description": r['chore_description'],
                "assignment_id": r['assignment_id'],
                "completed_at": r['completed_at'].isoformat() if r['completed_at'] else None,
            })

        result = []
        for ts in order[:20]:
            entry = grouped[ts]
            # Fetch stored scores + metrics for this round (saved at confirm time).
            cur.execute("""
                SELECT scores_json, metrics_json
                FROM allocation_results
                WHERE round_ts = %s
            """, (ts,))
            ar = cur.fetchone()
            result.append({
                "round_ts": entry['round_ts'],
                "date_label": entry['date_label'],
                "algorithm": entry['algorithm'],
                "scores": ar['scores_json'] if ar else {},
                "metrics": ar['metrics_json'] if ar else {},
                "assignments": list(entry['assignments'].values()),
            })
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── CONTRIBUTIONS ENDPOINT ──────────────────────────────────────────────────

@app.route('/api/households/<int:house_id>/contributions', methods=['GET'])
@require_auth
def get_contributions(house_id):
    """
    GET /api/households/<id>/contributions — Cumulative burden breakdown.
    Auth: Bearer token required. Any household member.
    Returns: [ { member_id, name, total_burden, percentage, fair_share_percentage } ]
             percentage = member's share of total household burden so far.
             fair_share_percentage = 100 / n_members (what equal would look like).
    """
    conn = get_db()
    try:
        if not is_member(conn, house_id, g.user_id):
            return jsonify({"error": "Not a member of this household"}), 403

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.id AS member_id, u.username AS name,
                   u.total_burden_accumulated AS total_burden
            FROM users u
            JOIN household_members hm ON hm.user_id = u.id
            WHERE hm.household_id = %s
        """, (house_id,))
        members = cur.fetchall()

        totals = [float(m['total_burden'] or 0) for m in members]
        total = sum(totals)
        fair_share = round(100 / len(members), 1) if members else 0

        result = []
        for m, t in zip(members, totals):
            pct = round(t / total * 100, 1) if total > 0 else fair_share
            result.append({
                "member_id": m['member_id'],
                "name": m['name'],
                "total_burden": round(t, 2),
                "percentage": pct,
                "fair_share_percentage": fair_share,
            })
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── JSON ALLOCATION (no auth, for testing) ──────────────────────────────────

@app.route('/api/allocate-json', methods=['POST'])
def allocate_json():
    """
    POST /api/allocate-json — Run allocation directly from JSON (no auth, no database).
    Used for: testing, demos, and the evaluation simulation pipeline.
    Body: { algorithm, members[], chores[], scores{ member: { chore: int } }, capabilities? }
    Returns: { algorithm, allocation[], metrics{}, explanation }
    Errors: 400 missing required fields or unknown algorithm
    Note: Unlike /allocate, this endpoint does NOT save to the database or update burden totals.
    """
    data = request.get_json() or {}
    members = data.get('members', [])
    chores = data.get('chores', [])
    scores = data.get('scores', {})
    capabilities = data.get('capabilities', {})
    algorithm_name = data.get('algorithm', 'bag-filling-practical')

    if not members or not chores or not scores:
        return jsonify({"error": "members, chores, and scores are required"}), 400

    try:
        capable = {}
        for m in members:
            cap = capabilities.get(m, chores[:])
            if isinstance(cap, list):
                capable[m] = {c: (c in cap) for c in chores}
            else:
                capable[m] = {c: cap.get(c, True) for c in chores}

        allocation = _run_algorithm(algorithm_name, scores, chores, capable)
        metrics = compute_all_metrics(scores, allocation)

        result_members = []
        for member_name, assigned in allocation.items():
            burden = sum(scores.get(member_name, {}).get(c, 0) for c in assigned)
            result_members.append({
                "member": member_name,
                "chores": assigned,
                "burden": burden,
                "chore_count": len(assigned),
            })

        return jsonify({
            "algorithm": algorithm_name,
            "allocation": result_members,
            "metrics": metrics,
            "explanation": EXPLANATIONS.get(algorithm_name, ""),
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ─── ADMIN TRANSFER ENDPOINT ────────────────────────────────────────────────

@app.route('/api/households/<int:house_id>/admin', methods=['PATCH'])
@require_auth
def change_admin(house_id):
    """
    PATCH /api/households/<id>/admin — Transfer admin role to another member.
    Auth: Bearer token required. Current admin only.
    Body: { new_admin_id }
    The new admin must already be a member of this household.
    Returns: { success: true, new_admin_id }
    Errors: 400 target not a member, 403 not current admin
    """
    conn = get_db()
    try:
        if not is_admin(conn, house_id, g.user_id):
            return jsonify({"error": "Only the current admin can transfer admin access"}), 403

        data = request.get_json() or {}
        new_admin_id = data.get('new_admin_id')
        if not new_admin_id:
            return jsonify({"error": "new_admin_id is required"}), 400

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT 1 FROM household_members WHERE household_id = %s AND user_id = %s",
            (house_id, int(new_admin_id))
        )
        if not cur.fetchone():
            return jsonify({"error": "New admin must be a member of this household"}), 400

        cur.execute(
            "UPDATE households SET admin_id = %s WHERE id = %s",
            (int(new_admin_id), house_id)
        )
        conn.commit()
        return jsonify({"success": True, "new_admin_id": int(new_admin_id)})
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── ACCOUNT MANAGEMENT ─────────────────────────────────────────────────────

@app.route('/api/account', methods=['PATCH'])
@require_auth
def update_account():
    """
    PATCH /api/account — Update the current user's display name and email.
    Auth: Bearer token required.
    Body: { name, email }
    Returns: { success: true, name, email }
    """
    conn = get_db()
    try:
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        if not name or not email:
            return jsonify({"error": "Name and email required"}), 400
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET username=%s, email=%s WHERE id=%s",
            (name, email, g.user_id)
        )
        conn.commit()
        return jsonify({"success": True, "name": name, "email": email})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/account', methods=['DELETE'])
@require_auth
def delete_account():
    """
    DELETE /api/account — Permanently delete the current user's account.
    Auth: Bearer token required.
    Removes the user from all households, deletes their burden scores and history,
    then deletes the user row. This is irreversible.
    Returns: { success: true }
    """
    conn = get_db()
    try:
        cur = conn.cursor()

        # 1. Wipe the user's own per-chore data first. This must happen BEFORE
        #    we delete any household, because dropping a household cascades to
        #    chores → burden_scores, but chores → assignment_history has no
        #    cascade rule and would block the household delete if any history
        #    rows remained.
        cur.execute("DELETE FROM burden_scores WHERE user_id = %s", (g.user_id,))
        cur.execute("DELETE FROM assignment_history WHERE user_id = %s", (g.user_id,))
        cur.execute("DELETE FROM household_members WHERE user_id = %s", (g.user_id,))

        # 2. For every household this user was admin of, either hand admin
        #    to the oldest remaining member or delete the household if they
        #    were the sole member.
        cur.execute("SELECT id FROM households WHERE admin_id = %s", (g.user_id,))
        admin_of = [r[0] for r in cur.fetchall()]
        for hid in admin_of:
            cur.execute("""
                SELECT user_id FROM household_members
                WHERE household_id = %s
                ORDER BY user_id ASC LIMIT 1
            """, (hid,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE households SET admin_id = %s WHERE id = %s",
                            (row[0], hid))
            else:
                cur.execute("DELETE FROM households WHERE id = %s", (hid,))

        # 3. Finally drop the user row itself.
        cur.execute("DELETE FROM users WHERE id = %s", (g.user_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ─── STATIC FILE SERVING (React production build) ───────────────────────────

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    build_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..', 'frontend', 'build'
    ))

    # Hashed JS/CSS bundles under static/ — content-addressed, safe to cache
    # for a year. New builds produce new filenames so this never goes stale.
    if path.startswith('static/'):
        file_path = os.path.join(build_dir, path)
        if os.path.exists(file_path):
            resp = send_from_directory(build_dir, path)
            resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            return resp

    # Other root files (favicon, manifest, robots.txt) — short cache
    if path and os.path.exists(os.path.join(build_dir, path)):
        resp = send_from_directory(build_dir, path)
        resp.headers['Cache-Control'] = 'public, max-age=3600'
        return resp

    # index.html (and every SPA fallback route) MUST NOT be cached. The HTML
    # references hashed bundles by name; if a browser holds onto an old
    # index.html after a deploy, it'd point at JS files that no longer exist.
    resp = send_from_directory(build_dir, 'index.html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma']        = 'no-cache'
    resp.headers['Expires']       = '0'
    return resp


# ─── START ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import os
    build_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..', 'frontend', 'build'
    ))
    if os.path.exists(build_dir):
        print(f"React build found at: {build_dir}")
        print("App running at: http://localhost:5000")
    else:
        print(f"WARNING: No React build found at {build_dir}")
        print("Run: cd frontend && npm run build")
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, port=5000)