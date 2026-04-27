"""
API Endpoint Tests — FairChore Flask Backend

Tests every major endpoint through the Flask test client, verifying:
  - Correct HTTP status codes for success and error cases
  - Response body shape and field presence
  - Auth enforcement (401 when no token, 403 when wrong role)
  - Business logic (score normalisation, allocation completeness)
  - Database side-effects (data actually saved, not just returned)

Run with: python scripts/run_tests.py
"""

import json
import sys
import os

import pytest
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.conftest import (
    register, login, auth_headers, get_token,
    create_household, add_chore, save_preferences, run_allocation,
    _TEST_DB,
)


# ══════════════════════════════════════════════════════════════════════════════
#  1. AUTH — REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

class TestRegistration:

    def test_register_success(self, client):
        res = register(client)
        assert res.status_code == 201
        data = json.loads(res.data)
        assert "token" in data
        assert "user" in data
        assert data["user"]["name"] == "Alice"

    def test_register_returns_jwt_token(self, client):
        res = register(client)
        token = json.loads(res.data)["token"]
        # JWT format: three base64 segments separated by dots
        assert token.count(".") == 2

    def test_register_duplicate_email_rejected(self, client):
        register(client)
        res = register(client)  # same email
        assert res.status_code == 409

    def test_register_short_password_rejected(self, client):
        res = register(client, password="abc")
        assert res.status_code == 400

    def test_register_missing_email_rejected(self, client):
        res = client.post("/api/register", json={"name": "Alice", "password": "password123"})
        assert res.status_code == 400

    def test_register_missing_name_rejected(self, client):
        res = client.post("/api/register", json={"email": "x@x.com", "password": "password123"})
        assert res.status_code == 400

    def test_register_missing_password_rejected(self, client):
        res = client.post("/api/register", json={"name": "Alice", "email": "x@x.com"})
        assert res.status_code == 400

    def test_register_empty_body_rejected(self, client):
        res = client.post("/api/register", json={})
        assert res.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  2. AUTH — LOGIN
# ══════════════════════════════════════════════════════════════════════════════

class TestLogin:

    def test_login_success(self, client):
        register(client)
        res = login(client)
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "token" in data
        assert "user" in data

    def test_login_wrong_password_rejected(self, client):
        register(client)
        res = login(client, password="wrongpassword")
        assert res.status_code == 401

    def test_login_unknown_email_rejected(self, client):
        res = login(client, email="nobody@test.com")
        assert res.status_code == 401

    def test_login_missing_fields_rejected(self, client):
        res = client.post("/api/login", json={"email": "alice@test.com"})
        assert res.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  3. AUTH — PROTECTED ROUTE ENFORCEMENT
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthEnforcement:

    def test_no_token_returns_401(self, client):
        res = client.get("/api/households")
        assert res.status_code == 401

    def test_malformed_token_returns_401(self, client):
        res = client.get("/api/households",
                         headers={"Authorization": "Bearer not.a.real.token"})
        assert res.status_code == 401

    def test_missing_bearer_prefix_returns_401(self, client):
        register(client)
        token = get_token(client)
        res = client.get("/api/households",
                         headers={"Authorization": token})  # no "Bearer "
        assert res.status_code == 401

    def test_valid_token_grants_access(self, client):
        register(client)
        token = get_token(client)
        res = client.get("/api/households", headers=auth_headers(token))
        assert res.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
#  4. HOUSEHOLDS
# ══════════════════════════════════════════════════════════════════════════════

class TestHouseholds:

    def test_create_household_success(self, client):
        register(client)
        token = get_token(client)
        res = create_household(client, token, "My Flat")
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["name"] == "My Flat"
        assert "join_code" in data
        assert len(data["join_code"]) == 6

    def test_create_household_missing_name_rejected(self, client):
        register(client)
        token = get_token(client)
        res = client.post("/api/households", json={}, headers=auth_headers(token))
        assert res.status_code == 400

    def test_list_households_initially_empty(self, client):
        register(client)
        token = get_token(client)
        res = client.get("/api/households", headers=auth_headers(token))
        assert res.status_code == 200
        assert json.loads(res.data) == []

    def test_list_households_shows_created(self, client):
        register(client)
        token = get_token(client)
        create_household(client, token, "My Flat")
        res = client.get("/api/households", headers=auth_headers(token))
        data = json.loads(res.data)
        assert len(data) == 1
        assert data[0]["name"] == "My Flat"

    def test_join_household_with_valid_code(self, client):
        # Admin creates household
        register(client, username="Admin", email="admin@test.com")
        admin_token = get_token(client, email="admin@test.com")
        h_res = create_household(client, admin_token)
        join_code = json.loads(h_res.data)["join_code"]

        # Second user joins
        register(client, username="Bob", email="bob@test.com")
        bob_token = get_token(client, email="bob@test.com")
        res = client.post("/api/households/join",
                          json={"code": join_code},
                          headers=auth_headers(bob_token))
        assert res.status_code == 200

    def test_join_household_invalid_code_rejected(self, client):
        register(client)
        token = get_token(client)
        res = client.post("/api/households/join",
                          json={"code": "XXXXXX"},
                          headers=auth_headers(token))
        assert res.status_code == 404

    def test_get_household_details(self, client):
        register(client)
        token = get_token(client)
        h_res = create_household(client, token)
        hid = json.loads(h_res.data)["id"]
        res = client.get(f"/api/households/{hid}", headers=auth_headers(token))
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "members" in data
        assert "chores" in data

    def test_non_member_cannot_access_household(self, client):
        register(client, username="Admin", email="admin@test.com")
        admin_token = get_token(client, email="admin@test.com")
        h_res = create_household(client, admin_token)
        hid = json.loads(h_res.data)["id"]

        register(client, username="Outsider", email="out@test.com")
        out_token = get_token(client, email="out@test.com")
        res = client.get(f"/api/households/{hid}", headers=auth_headers(out_token))
        assert res.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
#  5. CHORES
# ══════════════════════════════════════════════════════════════════════════════

class TestChores:

    def _setup_household(self, client):
        register(client)
        token = get_token(client)
        h_res = create_household(client, token)
        hid = json.loads(h_res.data)["id"]
        return token, hid

    def test_admin_can_add_chore(self, client):
        token, hid = self._setup_household(client)
        res = add_chore(client, token, hid, "Dishes")
        assert res.status_code == 201
        assert json.loads(res.data)["title"] == "Dishes"

    def test_any_member_can_add_chore(self, client):
        """Any household member (admin or not) can add a chore. Allocations
        stay admin-only, so anyone can grow the pool but only the admin
        decides when chores actually get assigned."""
        register(client, username="Admin", email="admin@test.com")
        admin_token = get_token(client, email="admin@test.com")
        h_res = create_household(client, admin_token)
        hid = json.loads(h_res.data)["id"]
        join_code = json.loads(h_res.data)["join_code"]

        register(client, username="Member", email="member@test.com")
        member_token = get_token(client, email="member@test.com")
        client.post("/api/households/join", json={"code": join_code},
                    headers=auth_headers(member_token))

        res = add_chore(client, member_token, hid, "Dishes")
        assert res.status_code == 201, res.data

    def test_non_member_cannot_add_chore(self, client):
        """A user who isn't in the household still can't add chores there."""
        register(client, username="Admin", email="admin@test.com")
        admin_token = get_token(client, email="admin@test.com")
        h_res = create_household(client, admin_token)
        hid = json.loads(h_res.data)["id"]
        register(client, username="Outsider", email="out@test.com")
        out_token = get_token(client, email="out@test.com")
        res = add_chore(client, out_token, hid, "Dishes")
        assert res.status_code == 403

    def test_add_chore_missing_title_rejected(self, client):
        token, hid = self._setup_household(client)
        res = client.post(f"/api/households/{hid}/chores", json={},
                          headers=auth_headers(token))
        assert res.status_code == 400

    def test_chore_appears_in_household_details(self, client):
        token, hid = self._setup_household(client)
        add_chore(client, token, hid, "Vacuuming")
        res = client.get(f"/api/households/{hid}", headers=auth_headers(token))
        chores = json.loads(res.data)["chores"]
        assert any(c["title"] == "Vacuuming" for c in chores)


# ══════════════════════════════════════════════════════════════════════════════
#  6. PREFERENCES (RATINGS → SCORE NORMALISATION)
# ══════════════════════════════════════════════════════════════════════════════

class TestPreferences:

    def _two_member_household(self, client):
        """Returns (admin_token, member_token, hid, [chore_ids])."""
        register(client, username="Admin", email="admin@test.com")
        admin_token = get_token(client, email="admin@test.com")
        h_res = create_household(client, admin_token)
        hid = json.loads(h_res.data)["id"]
        join_code = json.loads(h_res.data)["join_code"]

        register(client, username="Bob", email="bob@test.com")
        bob_token = get_token(client, email="bob@test.com")
        client.post("/api/households/join", json={"code": join_code},
                    headers=auth_headers(bob_token))

        chore_ids = []
        for title in ["Dishes", "Bins", "Laundry"]:
            r = add_chore(client, admin_token, hid, title)
            chore_ids.append(json.loads(r.data)["id"])

        return admin_token, bob_token, hid, chore_ids

    def test_save_preferences_success(self, client):
        token, _, hid, cids = self._two_member_household(client)
        ratings = {str(cids[0]): 1, str(cids[1]): 2, str(cids[2]): 3}
        res = save_preferences(client, token, hid, ratings)
        assert res.status_code == 200

    def test_saved_scores_sum_to_100(self, client, db):
        """Core invariant: normalised scores must sum to exactly 100."""
        token, _, hid, cids = self._two_member_household(client)
        ratings = {str(cids[0]): 1, str(cids[1]): 2, str(cids[2]): 3}
        save_preferences(client, token, hid, ratings)

        cur = db.cursor()
        cur.execute("""
            SELECT SUM(score) FROM burden_scores
            WHERE user_id = (SELECT id FROM users WHERE email = 'admin@test.com')
        """)
        total = cur.fetchone()[0]
        cur.close()
        assert abs(total - 100) <= 2, f"Scores summed to {total}, expected 100±2"

    def test_scores_stored_in_database(self, client, db):
        """Scores must be persisted, not just returned in the API response."""
        token, _, hid, cids = self._two_member_household(client)
        ratings = {str(cids[0]): 4, str(cids[1]): 2, str(cids[2]): 1}
        save_preferences(client, token, hid, ratings)

        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM burden_scores WHERE score > 0")
        count = cur.fetchone()[0]
        cur.close()
        assert count == 3

    def test_get_my_preferences_returns_saved_values(self, client):
        token, _, hid, cids = self._two_member_household(client)
        ratings = {str(cids[0]): 2, str(cids[1]): 3, str(cids[2]): 1}
        save_preferences(client, token, hid, ratings)
        res = client.get(f"/api/households/{hid}/my-preferences",
                         headers=auth_headers(token))
        assert res.status_code == 200
        data = json.loads(res.data)
        # All three chore IDs should be in the response
        for cid in cids:
            assert str(cid) in data

    def test_preferences_ready_requires_all_members(self, client):
        admin_token, _, hid, cids = self._two_member_household(client)
        # Only admin rates; Bob hasn't rated yet
        ratings = {str(cids[0]): 1, str(cids[1]): 2, str(cids[2]): 3}
        save_preferences(client, admin_token, hid, ratings)

        res = client.get(f"/api/households/{hid}/preferences-ready",
                         headers=auth_headers(admin_token))
        assert res.status_code == 200
        readiness = json.loads(res.data)
        ready_flags = [m["ready"] for m in readiness]
        assert not all(ready_flags), "Expected not all members ready (Bob hasn't rated)"

    def test_higher_dislike_rating_produces_higher_score(self, client, db):
        """Rating 4 (strongly dislike) must produce higher score than rating 1 (fine)."""
        token, _, hid, cids = self._two_member_household(client)
        # Rate chore[0] as 4 (hate) and chore[1] as 1 (fine)
        ratings = {str(cids[0]): 4, str(cids[1]): 1, str(cids[2]): 2}
        save_preferences(client, token, hid, ratings)

        cur = db.cursor()
        cur.execute("SELECT chore_id, score FROM burden_scores WHERE score > 0 ORDER BY chore_id")
        rows = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
        assert rows[cids[0]] > rows[cids[1]], "Rating 4 chore should score higher than rating 1 chore"


# ══════════════════════════════════════════════════════════════════════════════
#  7. ALLOCATION
# ══════════════════════════════════════════════════════════════════════════════

class TestAllocation:

    def _ready_household(self, client):
        """Two-member household with all preferences submitted, ready to allocate."""
        register(client, username="Admin", email="admin@test.com")
        admin_token = get_token(client, email="admin@test.com")
        h_res = create_household(client, admin_token)
        hid = json.loads(h_res.data)["id"]
        join_code = json.loads(h_res.data)["join_code"]

        register(client, username="Bob", email="bob@test.com")
        bob_token = get_token(client, email="bob@test.com")
        client.post("/api/households/join", json={"code": join_code},
                    headers=auth_headers(bob_token))

        chore_ids = []
        for title in ["Dishes", "Bins", "Laundry", "Vacuuming"]:
            r = add_chore(client, admin_token, hid, title)
            chore_ids.append(json.loads(r.data)["id"])

        admin_ratings = {str(chore_ids[0]): 1, str(chore_ids[1]): 3,
                         str(chore_ids[2]): 2, str(chore_ids[3]): 4}
        bob_ratings   = {str(chore_ids[0]): 3, str(chore_ids[1]): 1,
                         str(chore_ids[2]): 4, str(chore_ids[3]): 2}

        save_preferences(client, admin_token, hid, admin_ratings)
        save_preferences(client, bob_token, hid, bob_ratings)
        return admin_token, bob_token, hid, chore_ids

    def test_round_robin_allocation_returns_200(self, client):
        admin_token, _, hid, _ = self._ready_household(client)
        res = run_allocation(client, admin_token, hid, "round-robin")
        assert res.status_code == 200

    def test_top_trading_allocation_returns_200(self, client):
        admin_token, _, hid, _ = self._ready_household(client)
        res = run_allocation(client, admin_token, hid, "top-trading")
        assert res.status_code == 200

    def test_bag_filling_allocation_returns_200(self, client):
        admin_token, _, hid, _ = self._ready_household(client)
        res = run_allocation(client, admin_token, hid, "bag-filling-practical")
        assert res.status_code == 200

    def test_allocation_response_shape(self, client):
        admin_token, _, hid, chore_ids = self._ready_household(client)
        res = run_allocation(client, admin_token, hid, "round-robin")
        data = json.loads(res.data)
        assert "allocation" in data
        assert "metrics" in data
        assert "algorithm" in data

    def test_all_chores_assigned_exactly_once(self, client):
        """Each chore is now returned as {id, title} object, not a plain string."""
        admin_token, _, hid, chore_ids = self._ready_household(client)
        res = run_allocation(client, admin_token, hid, "round-robin")
        allocation = json.loads(res.data)["allocation"]
        # chores are now {id, title} objects
        assigned_ids = [c["id"] for member in allocation for c in member["chores"]]
        assert len(assigned_ids) == len(chore_ids), "Every chore must be assigned exactly once"
        assert len(assigned_ids) == len(set(assigned_ids)), "No chore should be assigned twice"

    def test_metrics_fields_present(self, client):
        admin_token, _, hid, _ = self._ready_household(client)
        res = run_allocation(client, admin_token, hid, "round-robin")
        metrics = json.loads(res.data)["metrics"]
        for field in ["ef1", "workload_ratio", "worst_mms_ratio", "all_assigned"]:
            assert field in metrics, f"Missing metric field: {field}"

    def test_allocation_saved_to_history_after_confirm(self, client, db):
        """Allocation is a dry run until the user confirms. Only /confirm writes to the DB."""
        admin_token, _, hid, chore_ids = self._ready_household(client)
        # Step 1: compute (dry run — nothing saved)
        res = run_allocation(client, admin_token, hid, "round-robin")
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM assignment_history")
        count_before = cur.fetchone()[0]
        assert count_before == 0, "Dry-run allocation must not write to the database"

        # Step 2: confirm — now it saves
        alloc_data = json.loads(res.data)
        confirm_res = client.post(f"/api/households/{hid}/allocate/confirm",
                                  json={"algorithm": alloc_data["algorithm"],
                                        "allocation": alloc_data["allocation"]},
                                  headers=auth_headers(admin_token))
        assert confirm_res.status_code == 200

        cur.execute("SELECT COUNT(*) FROM assignment_history")
        count = cur.fetchone()[0]
        cur.close()
        assert count == len(chore_ids), "Each assigned chore must appear in history"

    def test_non_admin_cannot_allocate(self, client):
        admin_token, bob_token, hid, _ = self._ready_household(client)
        res = run_allocation(client, bob_token, hid, "round-robin")
        assert res.status_code == 403

    def test_allocation_blocked_when_member_has_unrated_chores(self, client):
        """
        The backend enforces that ALL members must rate ALL chores before allocation
        can run. If any member has a chore with score=0, allocation returns 400.
        This prevents unfair allocations where some members have no preference data.
        """
        register(client, username="Admin", email="admin@test.com")
        admin_token = get_token(client, email="admin@test.com")
        h_res = create_household(client, admin_token)
        hid = json.loads(h_res.data)["id"]
        join_code = json.loads(h_res.data)["join_code"]

        register(client, username="Bob", email="bob@test.com")
        bob_token = get_token(client, email="bob@test.com")
        client.post("/api/households/join", json={"code": join_code},
                    headers=auth_headers(bob_token))

        cid = json.loads(add_chore(client, admin_token, hid, "Dishes").data)["id"]
        save_preferences(client, admin_token, hid, {str(cid): 2})
        # Bob has NOT rated Dishes (score=0) — allocation must be blocked
        res = run_allocation(client, admin_token, hid, "round-robin")
        assert res.status_code == 400, "Allocation should be blocked when any member has unrated chores"
        err = json.loads(res.data)
        assert "error" in err
        assert "missing" in err["error"].lower() or "unrated" in err["error"].lower() or "rated" in err["error"].lower()


# ══════════════════════════════════════════════════════════════════════════════
#  8. ALLOCATE-JSON (unauthenticated test endpoint)
# ══════════════════════════════════════════════════════════════════════════════

class TestAllocateJson:

    _payload = {
        "algorithm": "round-robin",
        "members": ["Alice", "Bob"],
        "chores": ["Dishes", "Bins", "Laundry"],
        "scores": {
            "Alice": {"Dishes": 40, "Bins": 20, "Laundry": 40},
            "Bob":   {"Dishes": 20, "Bins": 50, "Laundry": 30},
        }
    }

    def test_round_robin_returns_200(self, client):
        res = client.post("/api/allocate-json", json=self._payload)
        assert res.status_code == 200

    def test_top_trading_returns_200(self, client):
        payload = {**self._payload, "algorithm": "top-trading"}
        res = client.post("/api/allocate-json", json=payload)
        assert res.status_code == 200

    def test_bag_filling_practical_returns_200(self, client):
        payload = {**self._payload, "algorithm": "bag-filling-practical"}
        res = client.post("/api/allocate-json", json=payload)
        assert res.status_code == 200

    def test_all_chores_in_response(self, client):
        res = client.post("/api/allocate-json", json=self._payload)
        allocation = json.loads(res.data)["allocation"]
        assigned = [c for m in allocation for c in m["chores"]]
        assert set(assigned) == {"Dishes", "Bins", "Laundry"}

    def test_metrics_ef1_field_present(self, client):
        res = client.post("/api/allocate-json", json=self._payload)
        data = json.loads(res.data)
        assert "metrics" in data
        assert "ef1" in data["metrics"]

    def test_missing_scores_rejected(self, client):
        res = client.post("/api/allocate-json",
                          json={"algorithm": "round-robin",
                                "members": ["Alice"], "chores": ["Dishes"]})
        assert res.status_code == 400

    def test_invalid_algorithm_rejected(self, client):
        payload = {**self._payload, "algorithm": "nonexistent"}
        res = client.post("/api/allocate-json", json=payload)
        assert res.status_code == 400

    def test_capability_constraints_respected(self, client):
        """Member marked incapable must not receive that chore."""
        payload = {
            "algorithm": "round-robin",
            "members": ["Alice", "Bob"],
            "chores": ["Dishes", "Shopping"],
            "scores": {
                "Alice": {"Dishes": 30, "Shopping": 70},
                "Bob":   {"Dishes": 50, "Shopping": 50},
            },
            "capabilities": {"Alice": ["Dishes"], "Bob": ["Dishes", "Shopping"]}
        }
        res = client.post("/api/allocate-json", json=payload)
        assert res.status_code == 200
        allocation = json.loads(res.data)["allocation"]
        alice_entry = next(m for m in allocation if m["member"] == "Alice")
        # chores are now {id, title} objects — check by title
        alice_titles = [c["title"] if isinstance(c, dict) else c for c in alice_entry["chores"]]
        assert "Shopping" not in alice_titles, "Alice is incapable of Shopping"


# ══════════════════════════════════════════════════════════════════════════════
#  9. INTEGRATION — TWO-PHASE FLOW, JSONB, BURDEN AGREEMENT, CAPABILITY
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationFlows:
    """End-to-end regression tests covering the full allocation lifecycle.

    These tests guard the central design claims:
      - Two-phase allocation: dry-run → confirm → complete → next round sees
        only leftover chores.
      - allocation_results JSONB round-trip: scores and metrics saved at
        confirm time are replayed exactly by /history.
      - Burden-percentage reconciliation: the 'burden' field in /allocate
        matches the sum of household-average burden_at_time, which is what
        /burden-balance uses.  (Regression test for the mismatch bug.)
      - Capability constraint: is_capable=false flows DB → algorithm → output.
    """

    def _ready_household(self, client, chore_titles=None):
        """Two-member household with preferences submitted for all chores."""
        chore_titles = chore_titles or ["Dishes", "Bins", "Laundry", "Vacuuming"]
        register(client, username="Admin", email="admin@test.com")
        admin_token = get_token(client, email="admin@test.com")
        h_res = create_household(client, admin_token)
        hid = json.loads(h_res.data)["id"]
        join_code = json.loads(h_res.data)["join_code"]

        register(client, username="Bob", email="bob@test.com")
        bob_token = get_token(client, email="bob@test.com")
        client.post("/api/households/join", json={"code": join_code},
                    headers=auth_headers(bob_token))

        chore_ids = []
        for title in chore_titles:
            r = add_chore(client, admin_token, hid, title)
            chore_ids.append(json.loads(r.data)["id"])

        # Spread ratings across the 1–4 tiers within constraint caps.
        # For 4 chores: max 1 rating-4 and max 2 rating-(3 or 4) combined.
        admin_ratings = {str(chore_ids[0]): 1, str(chore_ids[1]): 3,
                         str(chore_ids[2]): 2, str(chore_ids[3]): 4}
        bob_ratings   = {str(chore_ids[0]): 3, str(chore_ids[1]): 1,
                         str(chore_ids[2]): 4, str(chore_ids[3]): 2}
        save_preferences(client, admin_token, hid, admin_ratings)
        save_preferences(client, bob_token, hid, bob_ratings)
        return admin_token, bob_token, hid, chore_ids

    # ── 9.1 Two-phase flow end-to-end ────────────────────────────────────────

    def test_two_phase_flow_dry_run_then_confirm_then_complete(self, client, db):
        """
        Full lifecycle under the one-shot allocation model:
          1. /allocate is a dry run — nothing in assignment_history yet.
          2. /allocate/confirm inserts rows with a shared confirmed_at timestamp.
          3. /assignments/<id>/complete stamps completed_at.
          4. A second /allocate has nothing left to allocate (all chores are
             already in assignment_history) → 400.
        """
        admin_token, bob_token, hid, chore_ids = self._ready_household(client)

        # Step 1: dry run
        res = run_allocation(client, admin_token, hid, "round-robin")
        assert res.status_code == 200
        alloc_data = json.loads(res.data)

        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM assignment_history")
        assert cur.fetchone()[0] == 0, "Dry-run must not write rows"

        # Step 2: confirm
        confirm = client.post(f"/api/households/{hid}/allocate/confirm",
                              json={"algorithm": alloc_data["algorithm"],
                                    "allocation": alloc_data["allocation"],
                                    "scores": alloc_data.get("scores", {}),
                                    "metrics": alloc_data.get("metrics", {})},
                              headers=auth_headers(admin_token))
        assert confirm.status_code == 200

        cur.execute("SELECT COUNT(*), COUNT(DISTINCT date_assigned) "
                    "FROM assignment_history")
        n_rows, n_rounds = cur.fetchone()
        assert n_rows == len(chore_ids), "Every assigned chore must be saved"
        assert n_rounds == 1, "All rows must share one confirmed_at timestamp"

        # Step 3: complete one chore (the assignee, not the admin).
        cur.execute("""
            SELECT ah.id, u.email
            FROM assignment_history ah
            JOIN users u ON u.id = ah.user_id
            WHERE u.email = 'bob@test.com'
            LIMIT 1
        """)
        bob_assignment_id, _ = cur.fetchone()

        complete = client.post(f"/api/assignments/{bob_assignment_id}/complete",
                               headers=auth_headers(bob_token))
        assert complete.status_code == 200

        cur.execute("SELECT completed_at FROM assignment_history WHERE id = %s",
                    (bob_assignment_id,))
        assert cur.fetchone()[0] is not None, "completed_at must be stamped"

        # Step 4: every chore is now in assignment_history (1 completed, 3 not).
        # Each chore is allocated exactly once, so the pool is empty → 400.
        res2 = run_allocation(client, admin_token, hid, "round-robin")
        assert res2.status_code == 400
        cur.close()

    def test_completed_chore_does_not_return_to_pool(self, client, db):
        """
        One-shot allocation model: a completed chore stays out of the pool
        forever. Even after the entire round is complete, /allocate returns 400
        (no unallocated chores). To redo something, the admin adds a fresh chore
        and rates it; that new chore is allocated independently.
        """
        admin_token, bob_token, hid, chore_ids = self._ready_household(client)

        res = run_allocation(client, admin_token, hid, "round-robin")
        alloc_data = json.loads(res.data)
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc_data["algorithm"],
                          "allocation": alloc_data["allocation"],
                          "scores": alloc_data.get("scores", {}),
                          "metrics": alloc_data.get("metrics", {})},
                    headers=auth_headers(admin_token))

        # Mark every assignment complete (via the owning user).
        cur = db.cursor()
        cur.execute("""
            SELECT ah.id, u.email FROM assignment_history ah
            JOIN users u ON u.id = ah.user_id
        """)
        rows = cur.fetchall()
        tokens = {"admin@test.com": admin_token, "bob@test.com": bob_token}
        for aid, email in rows:
            r = client.post(f"/api/assignments/{aid}/complete",
                            headers=auth_headers(tokens[email]))
            assert r.status_code == 200

        # Pool is empty — completed chores do NOT come back.
        res2 = run_allocation(client, admin_token, hid, "round-robin")
        assert res2.status_code == 400
        body2 = json.loads(res2.data)
        assert "No new chores" in body2["error"]

        # Add a fresh chore reusing the same name "Dishes" — both members rate
        # it, then the next /allocate should allocate exactly that one chore.
        new_chore = client.post(f"/api/households/{hid}/chores",
                                json={"title": "Dishes"},
                                headers=auth_headers(admin_token))
        new_id = json.loads(new_chore.data)["id"]
        save_preferences(client, admin_token, hid, {str(new_id): 2})
        save_preferences(client, bob_token, hid, {str(new_id): 2})

        res3 = run_allocation(client, admin_token, hid, "round-robin")
        assert res3.status_code == 200
        titles = [c["title"] for m in json.loads(res3.data)["allocation"]
                  for c in m["chores"]]
        assert titles == ["Dishes"], (
            "Only the freshly-added Dishes chore should be allocated; "
            "previously-completed chores stay out of the pool"
        )
        cur.close()

    # ── 9.2 allocation_results JSONB round-trip ──────────────────────────────

    def test_allocation_results_jsonb_saved_and_replayed_in_history(self, client, db):
        """
        Confirm must INSERT one row into allocation_results with the scores and
        metrics from the dry run.  /history must then read those back unchanged.
        This is the persistence layer for 'replay past rounds'.
        """
        admin_token, _, hid, _ = self._ready_household(client)

        res = run_allocation(client, admin_token, hid, "round-robin")
        alloc_data = json.loads(res.data)
        dry_scores = alloc_data["scores"]
        dry_metrics = alloc_data["metrics"]

        confirm = client.post(f"/api/households/{hid}/allocate/confirm",
                              json={"algorithm": alloc_data["algorithm"],
                                    "allocation": alloc_data["allocation"],
                                    "scores": dry_scores,
                                    "metrics": dry_metrics},
                              headers=auth_headers(admin_token))
        assert confirm.status_code == 200

        # DB: exactly one allocation_results row exists and matches.
        cur = db.cursor()
        cur.execute("""
            SELECT household_id, algorithm, scores_json, metrics_json
            FROM allocation_results
        """)
        rows = cur.fetchall()
        assert len(rows) == 1, "Confirm must insert exactly one allocation_results row"
        h, algo, s_json, m_json = rows[0]
        assert h == hid
        assert algo == "round-robin"
        assert s_json == dry_scores, "scores_json must round-trip unchanged"
        assert m_json.get("ef1") == dry_metrics.get("ef1"), \
            "metrics_json must preserve ef1 value"
        cur.close()

        # /history must return the same scores + metrics in the first round.
        hist_res = client.get(f"/api/households/{hid}/history",
                              headers=auth_headers(admin_token))
        assert hist_res.status_code == 200
        history = json.loads(hist_res.data)
        assert len(history) == 1
        assert history[0]["scores"] == dry_scores
        assert history[0]["metrics"].get("ef1") == dry_metrics.get("ef1")

    # ── 9.3 Burden-percentage agreement (regression for the mismatch bug) ────

    def test_burden_percentage_agrees_between_allocate_and_burden_balance(
            self, client, db):
        """
        The per-member 'burden' field in the /allocate response is the sum of
        chore.burden_at_time (household-average disutility).  /burden-balance
        after confirm uses EXACTLY the same burden_at_time values.  Therefore
        the burden-percentage split in the allocation preview MUST equal the
        burden-percentage split in /burden-balance.

        This is the regression test for the bug where /allocate used member's
        own preference sum while /burden-balance used the household average —
        so the home chart and the results chart disagreed.
        """
        admin_token, _, hid, _ = self._ready_household(client)

        res = run_allocation(client, admin_token, hid, "round-robin")
        alloc_data = json.loads(res.data)

        # Record the per-member burden proportions from the dry run.
        dry_burdens = {m["member_id"]: m["burden"] for m in alloc_data["allocation"]}
        total_dry = sum(dry_burdens.values())
        assert total_dry > 0
        dry_pct = {mid: (b / total_dry) * 100 for mid, b in dry_burdens.items()}

        # Confirm and then call /burden-balance.
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc_data["algorithm"],
                          "allocation": alloc_data["allocation"],
                          "scores": alloc_data.get("scores", {}),
                          "metrics": alloc_data.get("metrics", {})},
                    headers=auth_headers(admin_token))

        bb_res = client.get(f"/api/households/{hid}/burden-balance",
                            headers=auth_headers(admin_token))
        assert bb_res.status_code == 200
        weekly = json.loads(bb_res.data)["weekly"]
        total_bb = sum(m["burden"] for m in weekly)
        assert total_bb > 0
        bb_pct = {m["member_id"]: (m["burden"] / total_bb) * 100 for m in weekly}

        # Proportions must agree to within rounding (~0.5 pp is generous).
        for mid, pct in dry_pct.items():
            assert mid in bb_pct, f"Member {mid} missing from burden-balance"
            assert abs(pct - bb_pct[mid]) < 0.5, (
                f"Burden % mismatch for member {mid}: "
                f"allocate={pct:.2f}%, burden-balance={bb_pct[mid]:.2f}%"
            )

    # ── 9.4 Capability constraint DB → API → algorithm ───────────────────────

    def test_capability_flag_in_db_is_respected_by_allocate(self, client, db):
        """
        Setting burden_scores.is_capable = FALSE for a user+chore pair must
        prevent /allocate from ever assigning that chore to that user.
        This exercises the whole path: DB flag → /allocate reads it → builds
        capable[] matrix → algorithm honours it → response excludes.
        """
        admin_token, _, hid, chore_ids = self._ready_household(
            client,
            chore_titles=["Dishes", "Mowing Lawn", "Bins", "Laundry"]
        )
        mowing_id = chore_ids[1]

        # Mark admin incapable of mowing in the DB (e.g. injury).
        cur = db.cursor()
        cur.execute("""
            UPDATE burden_scores
            SET is_capable = FALSE
            WHERE chore_id = %s
              AND user_id = (SELECT id FROM users WHERE email = 'admin@test.com')
        """, (mowing_id,))
        cur.close()

        res = run_allocation(client, admin_token, hid, "round-robin")
        assert res.status_code == 200, res.data
        allocation = json.loads(res.data)["allocation"]
        admin_entry = next(m for m in allocation if m["member"] == "Admin")
        admin_titles = [c["title"] for c in admin_entry["chores"]]
        assert "Mowing Lawn" not in admin_titles, (
            "Admin is flagged incapable of Mowing Lawn — algorithm must not assign it"
        )
        # And Bob must have ended up with Mowing Lawn (only capable member).
        bob_entry = next(m for m in allocation if m["member"] == "Bob")
        bob_titles = [c["title"] for c in bob_entry["chores"]]
        assert "Mowing Lawn" in bob_titles, (
            "Mowing Lawn must go to Bob (only capable member)"
        )

    # ── 9.5 Preference inheritance when re-adding a chore by name ────────────

    def test_re_added_chore_inherits_preferences_from_prior_chore(self, client, db):
        """
        Adding a chore whose title already exists in the household (active,
        inactive, or in history) must inherit scores + capabilities from the
        most recent match, so the new chore is allocatable immediately
        without re-rating. This is what makes the 'redo by name' flow work.
        """
        admin_token, bob_token, hid, chore_ids = self._ready_household(client)

        # Find the admin and bob ids + the original Dishes chore id
        cur = db.cursor()
        cur.execute("SELECT id, email FROM users WHERE email IN "
                    "('admin@test.com', 'bob@test.com')")
        ids = {email: uid for uid, email in cur.fetchall()}
        admin_id, bob_id = ids['admin@test.com'], ids['bob@test.com']
        original_dishes_id = chore_ids[0]

        # Snapshot the original Dishes scores+caps for both members
        cur.execute("SELECT user_id, score, is_capable FROM burden_scores "
                    "WHERE chore_id = %s", (original_dishes_id,))
        original = {uid: (sc, cap) for uid, sc, cap in cur.fetchall()}
        assert admin_id in original and bob_id in original
        cur.close()

        # Run + confirm the first allocation so original Dishes goes to history
        res = run_allocation(client, admin_token, hid, "round-robin")
        alloc = json.loads(res.data)
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc["algorithm"],
                          "allocation": alloc["allocation"],
                          "scores": alloc.get("scores", {}),
                          "metrics": alloc.get("metrics", {})},
                    headers=auth_headers(admin_token))

        # Re-add a chore named exactly "Dishes". Inheritance copies scores for
        # OTHER members (Bob), but NOT for the requesting admin — they must
        # rate it themselves via the Preferences screen.
        r = client.post(f"/api/households/{hid}/chores",
                        json={"title": "Dishes"},
                        headers=auth_headers(admin_token))
        assert r.status_code == 201, r.data
        new = json.loads(r.data)
        assert new.get("inherited_from") == original_dishes_id

        cur = db.cursor()
        cur.execute("SELECT user_id, score, is_capable FROM burden_scores "
                    "WHERE chore_id = %s", (new["id"],))
        copied = {uid: (sc, cap) for uid, sc, cap in cur.fetchall()}
        cur.close()
        # Bob inherited the original score + capability.
        assert copied[bob_id] == original[bob_id]
        # Admin (the requester) starts with score=0; capability inherited.
        assert copied[admin_id][0] == 0, "Admin must start unrated for chores they add"
        assert copied[admin_id][1] == original[admin_id][1], "Capability is still inherited"

        # /allocate now blocks because admin hasn't rated the new chore.
        res_blocked = run_allocation(client, admin_token, hid, "round-robin")
        assert res_blocked.status_code == 400
        assert "rating(s) missing" in json.loads(res_blocked.data)["error"]

        # Admin rates the new chore — allocation now succeeds.
        save_preferences(client, admin_token, hid, {str(new["id"]): 2})
        res2 = run_allocation(client, admin_token, hid, "round-robin")
        assert res2.status_code == 200, res2.data
        titles = [c["title"] for m in json.loads(res2.data)["allocation"]
                  for c in m["chores"]]
        assert titles == ["Dishes"]


# ─── 10. AUDIT: untested endpoints + edge cases ───────────────────────────────

class TestAuditEndpoints:
    """Sweep coverage for endpoints not exercised elsewhere: /me, chore
    activate/delete, assignment toggle off, /chore-titles, admin transfer,
    account update + delete, history, contributions, allocate-json playground,
    new burden-balance shape."""

    def _setup_two_member_house(self, client):
        register(client, username="Admin", email="admin@a.com")
        admin_tok = get_token(client, email="admin@a.com")
        h = create_household(client, admin_tok, name="House")
        hid  = json.loads(h.data)["id"]
        code = json.loads(h.data)["join_code"]
        register(client, username="Bob", email="bob@a.com")
        bob_tok = get_token(client, email="bob@a.com")
        client.post("/api/households/join", json={"code": code},
                    headers=auth_headers(bob_tok))
        cids = []
        for t in ["A", "B"]:
            r = add_chore(client, admin_tok, hid, t)
            cids.append(json.loads(r.data)["id"])
        save_preferences(client, admin_tok, hid, {str(cids[0]): 2, str(cids[1]): 3})
        save_preferences(client, bob_tok,   hid, {str(cids[0]): 3, str(cids[1]): 2})
        return admin_tok, bob_tok, hid, cids

    def test_me_returns_username_and_email(self, client):
        register(client, email="me@x.com", username="Mia")
        tok = get_token(client, email="me@x.com")
        r = client.get("/api/me", headers=auth_headers(tok))
        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["email"] == "me@x.com"
        assert body["name"] == "Mia"

    def test_chore_titles_returns_distinct_titles_with_state(self, client):
        admin_tok, _, hid, _ = self._setup_two_member_house(client)
        r = client.get(f"/api/households/{hid}/chore-titles",
                       headers=auth_headers(admin_tok))
        assert r.status_code == 200
        titles = [s["title"] for s in json.loads(r.data)]
        assert sorted(titles) == ["A", "B"]
        # Both should be 'active' (not yet allocated)
        for s in json.loads(r.data):
            assert s["last_state"] == "active"

    def test_chore_titles_dedupes_case_insensitively(self, client):
        admin_tok, _, hid, _ = self._setup_two_member_house(client)
        # Re-add 'a' (lowercase) — must dedupe with existing 'A'
        client.post(f"/api/households/{hid}/chores",
                    json={"title": "a"}, headers=auth_headers(admin_tok))
        r = client.get(f"/api/households/{hid}/chore-titles",
                       headers=auth_headers(admin_tok))
        titles_lc = sorted(s["title"].lower() for s in json.loads(r.data))
        assert titles_lc == ["a", "b"], "Case-insensitive dedup expected"

    def test_chore_titles_marks_completed_state(self, client):
        admin_tok, bob_tok, hid, cids = self._setup_two_member_house(client)
        # Allocate, confirm, complete everything
        alloc = json.loads(run_allocation(client, admin_tok, hid, "round-robin").data)
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc["algorithm"], "allocation": alloc["allocation"],
                          "scores": alloc.get("scores", {}), "metrics": alloc.get("metrics", {})},
                    headers=auth_headers(admin_tok))
        # Mark each via owner
        hist = json.loads(client.get(f"/api/households/{hid}/history",
                                     headers=auth_headers(admin_tok)).data)
        for m in hist[0]["assignments"]:
            tok = admin_tok if m["member"] == "Admin" else bob_tok
            for c in m["chores"]:
                client.post(f"/api/assignments/{c['assignment_id']}/complete",
                            headers=auth_headers(tok))
        r = client.get(f"/api/households/{hid}/chore-titles",
                       headers=auth_headers(admin_tok))
        states = {s["title"]: s["last_state"] for s in json.loads(r.data)}
        assert states == {"A": "completed", "B": "completed"}

    def test_chore_delete_soft_deletes(self, client, db):
        admin_tok, _, hid, cids = self._setup_two_member_house(client)
        r = client.delete(f"/api/chores/{cids[0]}", headers=auth_headers(admin_tok))
        assert r.status_code == 200
        cur = db.cursor()
        cur.execute("SELECT is_active FROM chores WHERE id = %s", (cids[0],))
        assert cur.fetchone()[0] is False
        cur.close()

    def test_chore_delete_blocked_for_non_admin(self, client):
        admin_tok, bob_tok, hid, cids = self._setup_two_member_house(client)
        r = client.delete(f"/api/chores/{cids[0]}", headers=auth_headers(bob_tok))
        assert r.status_code == 403

    def test_chore_activate_flips_inactive_back_to_active(self, client, db):
        admin_tok, _, hid, cids = self._setup_two_member_house(client)
        client.delete(f"/api/chores/{cids[0]}", headers=auth_headers(admin_tok))
        r = client.patch(f"/api/chores/{cids[0]}/activate",
                         headers=auth_headers(admin_tok))
        assert r.status_code == 200
        cur = db.cursor()
        cur.execute("SELECT is_active FROM chores WHERE id = %s", (cids[0],))
        assert cur.fetchone()[0] is True
        cur.close()

    def test_assignment_toggle_off_clears_completed_at(self, client, db):
        admin_tok, bob_tok, hid, cids = self._setup_two_member_house(client)
        alloc = json.loads(run_allocation(client, admin_tok, hid, "round-robin").data)
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc["algorithm"], "allocation": alloc["allocation"],
                          "scores": alloc.get("scores", {}), "metrics": alloc.get("metrics", {})},
                    headers=auth_headers(admin_tok))
        cur = db.cursor()
        cur.execute("SELECT ah.id FROM assignment_history ah JOIN users u ON u.id=ah.user_id "
                    "WHERE u.email='bob@a.com' LIMIT 1")
        aid = cur.fetchone()[0]
        cur.close()
        # Mark done, then undo
        client.post(f"/api/assignments/{aid}/complete", headers=auth_headers(bob_tok))
        r = client.delete(f"/api/assignments/{aid}/complete", headers=auth_headers(bob_tok))
        assert r.status_code == 200
        cur = db.cursor()
        cur.execute("SELECT completed_at FROM assignment_history WHERE id = %s", (aid,))
        assert cur.fetchone()[0] is None, "DELETE must clear completed_at"
        cur.close()

    def test_assignment_complete_blocks_other_user(self, client):
        admin_tok, bob_tok, hid, cids = self._setup_two_member_house(client)
        alloc = json.loads(run_allocation(client, admin_tok, hid, "round-robin").data)
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc["algorithm"], "allocation": alloc["allocation"],
                          "scores": alloc.get("scores", {}), "metrics": alloc.get("metrics", {})},
                    headers=auth_headers(admin_tok))
        # admin tries to complete bob's assignment
        bob_alloc = next(m for m in alloc["allocation"] if m["member"] == "Bob")
        # find one of bob's assignment ids from /history
        hist = json.loads(client.get(f"/api/households/{hid}/history",
                                     headers=auth_headers(admin_tok)).data)
        bob_aids = [c["assignment_id"]
                    for r in hist for m in r["assignments"]
                    for c in m["chores"] if m["member"] == "Bob"]
        r = client.post(f"/api/assignments/{bob_aids[0]}/complete",
                        headers=auth_headers(admin_tok))
        assert r.status_code == 403

    def test_admin_transfer_changes_admin_id(self, client, db):
        admin_tok, _, hid, _ = self._setup_two_member_house(client)
        cur = db.cursor()
        cur.execute("SELECT id FROM users WHERE email='bob@a.com'")
        bob_id = cur.fetchone()[0]
        cur.close()
        r = client.patch(f"/api/households/{hid}/admin",
                         json={"new_admin_id": bob_id},
                         headers=auth_headers(admin_tok))
        assert r.status_code == 200
        cur = db.cursor()
        cur.execute("SELECT admin_id FROM households WHERE id=%s", (hid,))
        assert cur.fetchone()[0] == bob_id
        cur.close()

    def test_admin_transfer_blocked_for_non_admin(self, client, db):
        admin_tok, bob_tok, hid, _ = self._setup_two_member_house(client)
        cur = db.cursor()
        cur.execute("SELECT id FROM users WHERE email='bob@a.com'")
        bob_id = cur.fetchone()[0]
        cur.close()
        r = client.patch(f"/api/households/{hid}/admin",
                         json={"new_admin_id": bob_id},
                         headers=auth_headers(bob_tok))
        assert r.status_code == 403

    def test_account_patch_updates_name_and_email(self, client):
        register(client, email="orig@x.com", username="Orig")
        tok = get_token(client, email="orig@x.com")
        r = client.patch("/api/account",
                         json={"name": "Renamed", "email": "renamed@x.com"},
                         headers=auth_headers(tok))
        assert r.status_code == 200
        # Old email no longer logs in
        bad = client.post("/api/login",
                          json={"email": "orig@x.com", "password": "password123"})
        assert bad.status_code == 401
        # New email does
        good = client.post("/api/login",
                           json={"email": "renamed@x.com", "password": "password123"})
        assert good.status_code == 200

    def test_account_delete_removes_user_and_blocks_login(self, client, db):
        register(client, email="bye@x.com", username="Bye")
        tok = get_token(client, email="bye@x.com")
        r = client.delete("/api/account", headers=auth_headers(tok))
        assert r.status_code == 200
        cur = db.cursor()
        cur.execute("SELECT 1 FROM users WHERE email='bye@x.com'")
        assert cur.fetchone() is None
        cur.close()
        bad = client.post("/api/login",
                          json={"email": "bye@x.com", "password": "password123"})
        assert bad.status_code == 401

    def test_admin_can_delete_account_admin_transfers_to_other_member(self, client, db):
        """Admin of a household with other members deletes their account.
        Admin role must hand off to the next member; household survives."""
        admin_tok, bob_tok, hid, _ = self._setup_two_member_house(client)
        cur = db.cursor()
        cur.execute("SELECT id FROM users WHERE email='bob@a.com'")
        bob_id = cur.fetchone()[0]
        cur.close()

        r = client.delete("/api/account", headers=auth_headers(admin_tok))
        assert r.status_code == 200, r.data

        cur = db.cursor()
        cur.execute("SELECT 1 FROM users WHERE email='admin@a.com'")
        assert cur.fetchone() is None
        cur.execute("SELECT admin_id FROM households WHERE id = %s", (hid,))
        new_admin_id = cur.fetchone()[0]
        assert new_admin_id == bob_id, (
            "Household should still exist with Bob as the new admin, "
            f"got admin_id={new_admin_id}"
        )
        cur.close()

    def test_solo_admin_account_delete_also_deletes_household(self, client, db):
        """Solo admin (the only member) deletes their account.
        The household has nobody left, so it is deleted too."""
        register(client, email="lone@x.com", username="Lone")
        tok = get_token(client, email="lone@x.com")
        h = create_household(client, tok, name="Lone House")
        hid = json.loads(h.data)["id"]
        # Add a chore + a confirmed allocation so assignment_history has rows.
        cid = json.loads(add_chore(client, tok, hid, "X").data)["id"]
        save_preferences(client, tok, hid, {str(cid): 2})
        alloc = json.loads(run_allocation(client, tok, hid, "round-robin").data)
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc["algorithm"],
                          "allocation": alloc["allocation"],
                          "scores": alloc.get("scores", {}),
                          "metrics": alloc.get("metrics", {})},
                    headers=auth_headers(tok))

        r = client.delete("/api/account", headers=auth_headers(tok))
        assert r.status_code == 200, r.data

        cur = db.cursor()
        cur.execute("SELECT 1 FROM users WHERE email='lone@x.com'")
        assert cur.fetchone() is None
        cur.execute("SELECT 1 FROM households WHERE id = %s", (hid,))
        assert cur.fetchone() is None, "Solo household should be deleted"
        cur.execute("SELECT 1 FROM chores WHERE id = %s", (cid,))
        assert cur.fetchone() is None, "Cascade should remove the chore"
        cur.close()

    def test_history_returns_round_with_replay_data(self, client):
        admin_tok, _, hid, _ = self._setup_two_member_house(client)
        alloc = json.loads(run_allocation(client, admin_tok, hid, "round-robin").data)
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc["algorithm"], "allocation": alloc["allocation"],
                          "scores": alloc.get("scores", {}), "metrics": alloc.get("metrics", {})},
                    headers=auth_headers(admin_tok))
        r = client.get(f"/api/households/{hid}/history", headers=auth_headers(admin_tok))
        assert r.status_code == 200
        hist = json.loads(r.data)
        assert len(hist) == 1
        assert hist[0]["algorithm"] == "round-robin"
        assert "round_ts" in hist[0]
        assert any(m["member"] == "Bob" for m in hist[0]["assignments"])

    def test_contributions_returns_per_member_totals(self, client):
        admin_tok, bob_tok, hid, _ = self._setup_two_member_house(client)
        alloc = json.loads(run_allocation(client, admin_tok, hid, "round-robin").data)
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc["algorithm"], "allocation": alloc["allocation"],
                          "scores": alloc.get("scores", {}), "metrics": alloc.get("metrics", {})},
                    headers=auth_headers(admin_tok))
        r = client.get(f"/api/households/{hid}/contributions",
                       headers=auth_headers(admin_tok))
        assert r.status_code == 200, r.data

    def test_burden_balance_returns_cumulative_shape(self, client):
        admin_tok, _, hid, _ = self._setup_two_member_house(client)
        alloc = json.loads(run_allocation(client, admin_tok, hid, "round-robin").data)
        client.post(f"/api/households/{hid}/allocate/confirm",
                    json={"algorithm": alloc["algorithm"], "allocation": alloc["allocation"],
                          "scores": alloc.get("scores", {}), "metrics": alloc.get("metrics", {})},
                    headers=auth_headers(admin_tok))
        r = client.get(f"/api/households/{hid}/burden-balance",
                       headers=auth_headers(admin_tok))
        assert r.status_code == 200
        body = json.loads(r.data)
        # New cumulative shape: 'members' is the canonical field; legacy keys
        # ('daily','weekly','monthly') mirror it for backwards compatibility.
        assert "members" in body
        assert body["members"] == body["weekly"] == body["daily"] == body["monthly"]
        # Percentages must sum to ~ n_members × 100
        pct_sum = sum(m["percentage"] for m in body["members"])
        assert abs(pct_sum - 200) < 0.5, f"Two members → 200% total, got {pct_sum}"

    def test_allocate_json_playground_runs_without_db(self, client):
        # /allocate-json takes raw members/chores/scores, runs an algorithm,
        # returns allocation. No auth, no DB writes.
        r = client.post("/api/allocate-json", json={
            "algorithm": "round-robin",
            "members": ["Alice", "Bob"],
            "chores":  ["Dishes", "Bins"],
            "scores": {
                "Alice": {"Dishes": 10, "Bins": 5},
                "Bob":   {"Dishes": 5,  "Bins": 10},
            },
        })
        assert r.status_code == 200, r.data
        body = json.loads(r.data)
        assert "allocation" in body
        assert "metrics" in body

    def test_allocate_json_rejects_missing_fields(self, client):
        r = client.post("/api/allocate-json", json={"algorithm": "round-robin"})
        assert r.status_code == 400


class TestSecurityAndEdgeCases:
    """Cross-tenant access controls, malformed JWTs, and the unhappy paths
    that are easy to forget."""

    def test_other_household_cannot_be_read(self, client):
        register(client, email="a@x.com", username="A")
        a_tok = get_token(client, email="a@x.com")
        h = create_household(client, a_tok, name="A's house")
        a_hid = json.loads(h.data)["id"]
        register(client, email="b@x.com", username="B")
        b_tok = get_token(client, email="b@x.com")
        # B is not a member of A's house — must be 403
        r = client.get(f"/api/households/{a_hid}", headers=auth_headers(b_tok))
        assert r.status_code == 403

    def test_other_household_chore_cannot_be_deleted(self, client):
        register(client, email="a@x.com", username="A")
        a_tok = get_token(client, email="a@x.com")
        h = create_household(client, a_tok, name="A")
        a_hid = json.loads(h.data)["id"]
        a_chore = json.loads(add_chore(client, a_tok, a_hid, "X").data)["id"]
        register(client, email="b@x.com", username="B")
        b_tok = get_token(client, email="b@x.com")
        r = client.delete(f"/api/chores/{a_chore}", headers=auth_headers(b_tok))
        assert r.status_code in (403, 404)

    def test_xss_payload_in_chore_title_is_stored_verbatim(self, client):
        # Backend stores titles as-is via parameterized SQL; the frontend is
        # responsible for HTML-escaping. We only need to verify that storing
        # an HTML-y string doesn't crash the API and round-trips byte-perfect.
        register(client, email="x@x.com", username="X")
        tok = get_token(client, email="x@x.com")
        hid = json.loads(create_household(client, tok, name="H").data)["id"]
        payload = "<script>alert(1)</script>"
        r = add_chore(client, tok, hid, payload)
        assert r.status_code == 201
        assert json.loads(r.data)["title"] == payload
        # And the household read back gets the same string
        h = json.loads(client.get(f"/api/households/{hid}",
                                  headers=auth_headers(tok)).data)
        titles = [c["title"] for c in h["chores"]]
        assert payload in titles

    def test_sql_injection_attempt_in_chore_title_is_just_a_string(self, client, db):
        register(client, email="s@x.com", username="S")
        tok = get_token(client, email="s@x.com")
        hid = json.loads(create_household(client, tok, name="H").data)["id"]
        nasty = "'); DROP TABLE chores; --"
        r = add_chore(client, tok, hid, nasty)
        assert r.status_code == 201
        # If injection had worked, this query would fail. If it stored the
        # literal string, it succeeds and we read it back.
        cur = db.cursor()
        cur.execute("SELECT 1 FROM chores WHERE title = %s", (nasty,))
        assert cur.fetchone() is not None
        cur.close()

    def test_jwt_with_tampered_payload_is_rejected(self, client):
        register(client, email="t@x.com", username="T")
        tok = get_token(client, email="t@x.com")
        # Flip a character in the payload section (between the two dots)
        head, body, sig = tok.split(".")
        bad_body = body[:-1] + ("A" if body[-1] != "A" else "B")
        bad_tok = f"{head}.{bad_body}.{sig}"
        r = client.get("/api/me", headers=auth_headers(bad_tok))
        assert r.status_code == 401

    def test_single_member_household_allocates_everything_to_that_member(self, client):
        register(client, email="solo@x.com", username="Solo")
        tok = get_token(client, email="solo@x.com")
        hid = json.loads(create_household(client, tok, name="H").data)["id"]
        cids = [json.loads(add_chore(client, tok, hid, t).data)["id"]
                for t in ["A", "B", "C"]]
        save_preferences(client, tok, hid, {str(cids[0]): 1, str(cids[1]): 2, str(cids[2]): 3})
        r = run_allocation(client, tok, hid, "round-robin")
        assert r.status_code == 200
        alloc = json.loads(r.data)["allocation"]
        assert len(alloc) == 1
        assert alloc[0]["chore_count"] == 3

    def test_allocation_results_round_ts_uniqueness_enforced_by_db(self, client, db):
        """
        The schema has UNIQUE (round_ts) on allocation_results. The /confirm
        endpoint stamps confirmed_at = NOW() server-side, so back-to-back
        confirms generate distinct timestamps and produce distinct rounds —
        the UI is responsible for disabling the Confirm button while a request
        is in flight, and exact-duplicate timestamps would only happen via
        clock weirdness or direct DB writes.

        This test verifies the safety net: if two rows somehow share a
        round_ts, the second INSERT is silently dropped via ON CONFLICT
        DO NOTHING — no duplicate, no exception.
        """
        from datetime import datetime, timezone
        cur = db.cursor()
        # Set up a household just so we have a valid household_id FK.
        register(client, email="u@x.com", username="U")
        tok = get_token(client, email="u@x.com")
        hid = json.loads(create_household(client, tok, name="H").data)["id"]

        ts = datetime.now(timezone.utc)
        cur.execute("""
            INSERT INTO allocation_results (household_id, round_ts, algorithm, scores_json, metrics_json)
            VALUES (%s, %s, 'round-robin', '{}'::jsonb, '{}'::jsonb)
            ON CONFLICT (round_ts) DO NOTHING
        """, (hid, ts))
        cur.execute("""
            INSERT INTO allocation_results (household_id, round_ts, algorithm, scores_json, metrics_json)
            VALUES (%s, %s, 'top-trading', '{}'::jsonb, '{}'::jsonb)
            ON CONFLICT (round_ts) DO NOTHING
        """, (hid, ts))
        cur.execute("SELECT COUNT(*) FROM allocation_results WHERE round_ts = %s", (ts,))
        assert cur.fetchone()[0] == 1, "ON CONFLICT must dedupe identical round_ts"
        cur.close()

    def test_spa_fallback_returns_html_for_unknown_path(self, client):
        # Unknown non-API path should fall back to index.html (or 404 if no
        # build present). Tests the /<path:path> catch-all.
        r = client.get("/some/spa/route/that/does/not/exist")
        # Either it serves index.html (200) or it 404s gracefully —
        # but it MUST NOT 500.
        assert r.status_code in (200, 404)
        assert r.status_code != 500
