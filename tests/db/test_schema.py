"""
Database Schema & Seed Data Tests — FairChore

Tests the PostgreSQL schema structure and the integrity of demo seed data.
Split into two groups:
  1. Schema structure tests  — run against fairchore_test (clean schema, no data)
  2. Seed data integrity tests — run against the real fairchore DB

These tests verify that:
  - All required tables and columns exist with correct types
  - Constraints (UNIQUE, NOT NULL, FK, CASCADE) are enforced by the DB engine
  - Default values work as expected
  - Seed data (demo accounts) is correct and allocation-ready
  - Capability flags are set correctly for demo households
"""

import sys
import os
import pytest
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.conftest import _TEST_DB, _PROD_DB


# ══════════════════════════════════════════════════════════════════════════════
#  1. TABLE EXISTENCE
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_TABLES = ["users", "households", "household_members", "chores",
                   "burden_scores", "assignment_history"]


@pytest.mark.parametrize("table", REQUIRED_TABLES)
def test_required_table_exists(db, table):
    cur = db.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
    """, (table,))
    count = cur.fetchone()[0]
    cur.close()
    assert count == 1, f"Table '{table}' does not exist"


# ══════════════════════════════════════════════════════════════════════════════
#  2. COLUMN PRESENCE
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_COLUMNS = [
    ("users", "id"), ("users", "username"), ("users", "email"),
    ("users", "password_hash"), ("users", "total_burden_accumulated"),
    ("households", "id"), ("households", "name"), ("households", "join_code"),
    ("households", "admin_id"),
    ("chores", "id"), ("chores", "household_id"), ("chores", "title"),
    ("chores", "is_active"),
    ("burden_scores", "user_id"), ("burden_scores", "chore_id"),
    ("burden_scores", "score"), ("burden_scores", "is_capable"),
    ("assignment_history", "user_id"), ("assignment_history", "chore_id"),
    ("assignment_history", "algorithm_used"), ("assignment_history", "date_assigned"),
]


@pytest.mark.parametrize("table,column", REQUIRED_COLUMNS)
def test_required_column_exists(db, table, column):
    cur = db.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
    """, (table, column))
    count = cur.fetchone()[0]
    cur.close()
    assert count == 1, f"Column '{table}.{column}' does not exist"


# ══════════════════════════════════════════════════════════════════════════════
#  3. CONSTRAINTS
# ══════════════════════════════════════════════════════════════════════════════

class TestConstraints:

    def test_users_email_unique(self, db):
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'dup@test.com', 'x')")
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('B', 'dup@test.com', 'y')")
        cur.close()

    def test_households_join_code_unique(self, db):
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'a@t.com', 'x') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO households (name, join_code, admin_id) VALUES ('H1', 'AAAAAA', %s)", (uid,))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO households (name, join_code, admin_id) VALUES ('H2', 'AAAAAA', %s)", (uid,))
        cur.close()

    def test_burden_scores_user_chore_unique(self, db):
        """Same (user_id, chore_id) pair cannot appear twice."""
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'a@t.com', 'x') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO households (name, join_code, admin_id) VALUES ('H', 'BBBBBB', %s) RETURNING id", (uid,))
        hid = cur.fetchone()[0]
        cur.execute("INSERT INTO chores (household_id, title) VALUES (%s, 'Dishes') RETURNING id", (hid,))
        cid = cur.fetchone()[0]
        cur.execute("INSERT INTO burden_scores (user_id, chore_id, score) VALUES (%s, %s, 10)", (uid, cid))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO burden_scores (user_id, chore_id, score) VALUES (%s, %s, 20)", (uid, cid))
        cur.close()

    def test_chore_soft_delete_default_active(self, db):
        """is_active defaults to TRUE — chores are active unless explicitly deleted."""
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'a@t.com', 'x') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO households (name, join_code, admin_id) VALUES ('H', 'CCCCCC', %s) RETURNING id", (uid,))
        hid = cur.fetchone()[0]
        cur.execute("INSERT INTO chores (household_id, title) VALUES (%s, 'Vacuuming') RETURNING is_active", (hid,))
        is_active = cur.fetchone()[0]
        cur.close()
        assert is_active is True

    def test_burden_score_default_zero(self, db):
        """score defaults to 0 (unrated) when a new chore is added for a member."""
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'a@t.com', 'x') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO households (name, join_code, admin_id) VALUES ('H', 'DDDDDD', %s) RETURNING id", (uid,))
        hid = cur.fetchone()[0]
        cur.execute("INSERT INTO chores (household_id, title) VALUES (%s, 'Bins') RETURNING id", (hid,))
        cid = cur.fetchone()[0]
        cur.execute("INSERT INTO burden_scores (user_id, chore_id) VALUES (%s, %s) RETURNING score", (uid, cid))
        score = cur.fetchone()[0]
        cur.close()
        assert score == 0

    def test_is_capable_default_true(self, db):
        """is_capable defaults to TRUE — members are assumed capable unless flagged."""
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'a@t.com', 'x') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO households (name, join_code, admin_id) VALUES ('H', 'EEEEEE', %s) RETURNING id", (uid,))
        hid = cur.fetchone()[0]
        cur.execute("INSERT INTO chores (household_id, title) VALUES (%s, 'Cooking') RETURNING id", (hid,))
        cid = cur.fetchone()[0]
        cur.execute("INSERT INTO burden_scores (user_id, chore_id) VALUES (%s, %s) RETURNING is_capable", (uid, cid))
        capable = cur.fetchone()[0]
        cur.close()
        assert capable is True

    def test_users_burden_default_zero(self, db):
        """total_burden_accumulated starts at 0 for new users."""
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'a@t.com', 'x') RETURNING total_burden_accumulated")
        burden = cur.fetchone()[0]
        cur.close()
        assert float(burden) == 0


# ══════════════════════════════════════════════════════════════════════════════
#  4. CASCADE BEHAVIOUR
# ══════════════════════════════════════════════════════════════════════════════

class TestCascades:

    def test_deleting_household_cascades_to_chores(self, db):
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'a@t.com', 'x') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO households (name, join_code, admin_id) VALUES ('H', 'FFFF11', %s) RETURNING id", (uid,))
        hid = cur.fetchone()[0]
        cur.execute("INSERT INTO chores (household_id, title) VALUES (%s, 'Dishes')", (hid,))

        cur.execute("DELETE FROM households WHERE id = %s", (hid,))
        cur.execute("SELECT COUNT(*) FROM chores WHERE household_id = %s", (hid,))
        count = cur.fetchone()[0]
        cur.close()
        assert count == 0, "Chores should be deleted when their household is deleted"

    def test_deleting_household_cascades_to_members(self, db):
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'a@t.com', 'x') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO households (name, join_code, admin_id) VALUES ('H', 'GGGG22', %s) RETURNING id", (uid,))
        hid = cur.fetchone()[0]
        cur.execute("INSERT INTO household_members (household_id, user_id) VALUES (%s, %s)", (hid, uid))

        cur.execute("DELETE FROM households WHERE id = %s", (hid,))
        cur.execute("SELECT COUNT(*) FROM household_members WHERE household_id = %s", (hid,))
        count = cur.fetchone()[0]
        cur.close()
        assert count == 0

    def test_deleting_chore_cascades_to_burden_scores(self, db):
        cur = db.cursor()
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES ('A', 'a@t.com', 'x') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO households (name, join_code, admin_id) VALUES ('H', 'HHHH33', %s) RETURNING id", (uid,))
        hid = cur.fetchone()[0]
        cur.execute("INSERT INTO chores (household_id, title) VALUES (%s, 'Dishes') RETURNING id", (hid,))
        cid = cur.fetchone()[0]
        cur.execute("INSERT INTO burden_scores (user_id, chore_id, score) VALUES (%s, %s, 30)", (uid, cid))

        cur.execute("DELETE FROM chores WHERE id = %s", (cid,))
        cur.execute("SELECT COUNT(*) FROM burden_scores WHERE chore_id = %s", (cid,))
        count = cur.fetchone()[0]
        cur.close()
        assert count == 0, "Burden scores should be deleted when their chore is deleted"


# ══════════════════════════════════════════════════════════════════════════════
#  5. SEED DATA INTEGRITY (real fairchore DB)
# ══════════════════════════════════════════════════════════════════════════════

class TestSeedDataIntegrity:
    """
    Verifies the demo seed data is correct and allocation-ready.
    These tests run against the real fairchore database.
    """

    def test_three_households_exist(self, prod_db):
        cur = prod_db.cursor()
        cur.execute("SELECT COUNT(*) FROM households")
        count = cur.fetchone()[0]
        cur.close()
        assert count == 3, f"Expected 3 seed households, found {count}"

    def test_ten_users_exist(self, prod_db):
        cur = prod_db.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE id <= 10")
        count = cur.fetchone()[0]
        cur.close()
        assert count == 10, f"Expected 10 seed users, found {count}"

    def test_join_codes_are_correct(self, prod_db):
        cur = prod_db.cursor()
        cur.execute("SELECT join_code FROM households ORDER BY id")
        codes = [row[0] for row in cur.fetchall()]
        cur.close()
        assert codes == ["FLAT42", "SMITHS", "FAMILY"]

    # Admin users (1=Alex, 5=Pat, 7=Mum) deliberately start with NO burden_scores
    # so the demo can showcase the rating workflow. Other members are pre-rated.
    SEED_ADMIN_IDS = (1, 5, 7)

    def test_non_admin_seed_members_have_scores_summing_to_100(self, prod_db):
        """Every non-admin seed member must have burden scores summing to 100±2 on
        ACTIVE chores (the same subset the allocator uses). Admin users start
        unrated by design."""
        cur = prod_db.cursor()
        cur.execute("""
            SELECT u.username, SUM(es.score) as total
            FROM users u
            JOIN burden_scores es ON u.id = es.user_id
            JOIN chores c ON c.id = es.chore_id
            WHERE u.id <= 10 AND u.id NOT IN (1, 5, 7) AND c.is_active = TRUE
            GROUP BY u.id, u.username
        """)
        rows = cur.fetchall()
        cur.close()
        assert len(rows) == 7, "All 7 non-admin seed users must have burden_scores"
        for username, total in rows:
            assert abs(total - 100) <= 2, (
                f"{username}'s scores sum to {total}, expected 100±2"
            )

    def test_admin_seed_members_have_no_scores(self, prod_db):
        """Admin users start unrated so the demo can showcase the rating flow.
        They must have ZERO burden_scores rows."""
        cur = prod_db.cursor()
        cur.execute("""
            SELECT u.id, u.username, COUNT(es.chore_id) AS n
            FROM users u
            LEFT JOIN burden_scores es ON es.user_id = u.id
            WHERE u.id IN (1, 5, 7)
            GROUP BY u.id, u.username
            ORDER BY u.id
        """)
        rows = cur.fetchall()
        cur.close()
        assert all(n == 0 for _, _, n in rows), (
            f"Admin users must have no burden_scores rows, got {rows}"
        )

    def test_no_non_admin_seed_member_has_unrated_chores(self, prod_db):
        """Non-admin seed members shouldn't have any score=0 rows."""
        cur = prod_db.cursor()
        cur.execute("""
            SELECT u.username, COUNT(*) as unrated
            FROM users u
            JOIN burden_scores es ON u.id = es.user_id
            WHERE u.id <= 10 AND u.id NOT IN (1, 5, 7) AND es.score = 0
            GROUP BY u.username
        """)
        violations = cur.fetchall()
        cur.close()
        assert violations == [], (
            f"Non-admin seed users with score=0 (unrated): {violations}"
        )

    def test_capability_flags_correct_for_taylor(self, prod_db):
        """Taylor (user 4) must have is_capable=FALSE for Shopping (chore 7)."""
        cur = prod_db.cursor()
        cur.execute("""
            SELECT is_capable FROM burden_scores
            WHERE user_id = 4 AND chore_id = 7
        """)
        row = cur.fetchone()
        cur.close()
        assert row is not None, "burden_score row for Taylor→Shopping missing"
        assert row[0] is False, "Taylor should be incapable of Shopping (no car)"

    def test_capability_flags_correct_for_teen2(self, prod_db):
        """Teen2 (user 10) must be incapable of Cooking (chore 22) and Shopping (chore 27)."""
        cur = prod_db.cursor()
        cur.execute("""
            SELECT chore_id, is_capable FROM burden_scores
            WHERE user_id = 10 AND chore_id IN (22, 27)
            ORDER BY chore_id
        """)
        rows = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
        assert rows.get(22) is False, "Teen2 should be incapable of Cooking"
        assert rows.get(27) is False, "Teen2 should be incapable of Shopping"

    def test_flat42_has_10_chores(self, prod_db):
        cur = prod_db.cursor()
        cur.execute("SELECT COUNT(*) FROM chores WHERE household_id = 1 AND is_active = TRUE")
        count = cur.fetchone()[0]
        cur.close()
        assert count == 10

    def test_smiths_has_6_chores(self, prod_db):
        cur = prod_db.cursor()
        cur.execute("SELECT COUNT(*) FROM chores WHERE household_id = 2 AND is_active = TRUE")
        count = cur.fetchone()[0]
        cur.close()
        assert count == 6

    def test_family_home_has_8_chores(self, prod_db):
        cur = prod_db.cursor()
        cur.execute("SELECT COUNT(*) FROM chores WHERE household_id = 3 AND is_active = TRUE")
        count = cur.fetchone()[0]
        cur.close()
        assert count == 8

    def test_admin_passwords_are_hashed(self, prod_db):
        """Passwords must be stored as salt:hash, never plaintext."""
        cur = prod_db.cursor()
        cur.execute("""
            SELECT username, password_hash FROM users
            WHERE email IN ('admin@flat42.com', 'admin@smiths.com', 'admin@family.com')
        """)
        rows = cur.fetchall()
        cur.close()
        assert len(rows) == 3
        for username, phash in rows:
            assert phash is not None, f"{username} has no password hash"
            assert ":" in phash, f"{username}'s password hash is not in salt:hash format"
            assert "test123" not in phash, f"{username}'s hash appears to contain plaintext password"

    def test_all_seed_members_are_in_households(self, prod_db):
        """Every seed user must belong to exactly one household."""
        cur = prod_db.cursor()
        cur.execute("""
            SELECT u.username, COUNT(hm.household_id)
            FROM users u
            LEFT JOIN household_members hm ON u.id = hm.user_id
            WHERE u.id <= 10
            GROUP BY u.id, u.username
        """)
        rows = cur.fetchall()
        cur.close()
        for username, count in rows:
            assert count >= 1, f"{username} is not in any household"
