-- FairChore Database Schema
-- Full schema with auth, households, chores, preferences, and seed data

-- Drop existing tables (clean start)
DROP TABLE IF EXISTS allocation_results CASCADE;
DROP TABLE IF EXISTS assignment_history CASCADE;
DROP TABLE IF EXISTS burden_scores CASCADE;
DROP TABLE IF EXISTS chores CASCADE;
DROP TABLE IF EXISTS household_members CASCADE;
DROP TABLE IF EXISTS households CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- 1. Users
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(512),
    total_burden_accumulated NUMERIC(12,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 2. Households
CREATE TABLE households (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    join_code VARCHAR(10) UNIQUE NOT NULL,
    admin_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. Household members (many-to-many)
CREATE TABLE household_members (
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (household_id, user_id)
);

-- 4. Chores
CREATE TABLE chores (
    id SERIAL PRIMARY KEY,
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 5. Burden scores (preference matrix)
-- score: higher = dislikes more (100-point budget distributed across all chores)
-- is_capable: false = this member physically cannot do this chore
CREATE TABLE burden_scores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    chore_id INTEGER REFERENCES chores(id) ON DELETE CASCADE,
    score INTEGER DEFAULT 0,
    is_capable BOOLEAN DEFAULT TRUE,
    UNIQUE(user_id, chore_id)
);

-- 6. Assignment history
-- date_assigned is TIMESTAMP (not DATE) so multiple allocation runs on the
-- same day each get a unique timestamp, making each round distinguishable.
-- All rows belonging to one confirmed allocation share the same timestamp
-- (passed in from the confirm endpoint so they batch correctly).
-- burden_at_time stores the household average burden (= average of all members'
-- preference scores) for the chore at the moment of allocation. NUMERIC to
-- preserve fractional precision across many rounds.
CREATE TABLE assignment_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    chore_id INTEGER REFERENCES chores(id),
    burden_at_time NUMERIC(10,2),
    algorithm_used VARCHAR(50),
    date_assigned TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP NULL DEFAULT NULL
);

-- Stores the full scores matrix and metrics from each confirmed allocation
-- so past allocation results can be viewed with full comparison data.
CREATE TABLE allocation_results (
    id SERIAL PRIMARY KEY,
    household_id INTEGER REFERENCES households(id) ON DELETE CASCADE,
    round_ts TIMESTAMP UNIQUE NOT NULL,
    algorithm VARCHAR(50),
    scores_json JSONB NOT NULL DEFAULT '{}',
    metrics_json JSONB NOT NULL DEFAULT '{}'
);


-- ═══════════════════════════════════════════════════════════════════════
--  SEED DATA
--
--  Password hashes computed with:
--    import hashlib
--    def hash_with_salt(password, salt_hex):
--        h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt_hex.encode(), 260000)
--        return salt_hex + ':' + h.hex()
--
--  hash_with_salt('test123', 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6')
--    => a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6:d8db8f92ccb594b8ccd7a9cc1025442de82ac7d300a558cad310e28adaddb472
--  hash_with_salt('test123', 'b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7')
--    => b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7:0ec3dbdd663a47476ed70f9df9d633382abaaaf70369556649c95a68e907b912
--  hash_with_salt('test123', 'c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8')
--    => c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8:ecb19bc446d6b31a404273d5ffc18bf50110d87c31eebf7025ab573122952713
-- ═══════════════════════════════════════════════════════════════════════

-- Admin users for the 3 test households.
-- total_burden_accumulated is intentionally 0 for everyone — burden grows
-- naturally as members confirm allocations, so the displayed burden bar and
-- the algorithm's picking order share a single source of truth.
INSERT INTO users (id, username, email, password_hash, total_burden_accumulated) VALUES
(1,  'Abdul',   'admin@flat42.com',  'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6:d8db8f92ccb594b8ccd7a9cc1025442de82ac7d300a558cad310e28adaddb472', 0),
(2,  'Lara', null, null, 0),
(3,  'Sam',    null, null, 0),
(4,  'Sara', null, null, 0),
(5,  'Pat',    'admin@smiths.com',  'b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7:0ec3dbdd663a47476ed70f9df9d633382abaaaf70369556649c95a68e907b912', 0),
(6,  'Robin',  null, null, 0),
(7,  'Mum',    'admin@family.com',  'c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8:ecb19bc446d6b31a404273d5ffc18bf50110d87c31eebf7025ab573122952713', 0),
(8,  'Dad',    null, null, 0),
(9,  'Teen1',  null, null, 0),
(10, 'Teen2',  null, null, 0);

SELECT setval('users_id_seq', 10);

-- ═══════════════════════════════════════════════════════════════════════
--  Household 1 — "Flat 42" (4 students, 10 chores)
-- ═══════════════════════════════════════════════════════════════════════

INSERT INTO households (id, name, join_code, admin_id) VALUES (1, 'Flat 42', 'FLAT42', 1);

INSERT INTO household_members (household_id, user_id) VALUES
(1, 1), (1, 2), (1, 3), (1, 4);

INSERT INTO chores (id, household_id, title, is_active) VALUES
(1,  1, 'Vacuuming',      TRUE),
(2,  1, 'Dishes',         TRUE),
(3,  1, 'Bins',           TRUE),
(4,  1, 'Bathroom',       TRUE),
(5,  1, 'Kitchen',        TRUE),
(6,  1, 'Laundry',        TRUE),
(7,  1, 'Shopping',       TRUE),
(8,  1, 'Mopping',        TRUE),
(9,  1, 'Dusting',        TRUE),
(10, 1, 'Oven cleaning',  TRUE);

-- Burden scores for Flat 42 (each member sums to 100)
-- IMPROVED for fair allocation: balanced preferences, no universally-hated chores
-- Alex: prefers cooking/kitchen, dislikes heavy cleaning (vacuuming, mopping)
INSERT INTO burden_scores (user_id, chore_id, score, is_capable) VALUES
(1, 1,  14, TRUE),   -- Vacuuming (dislikes)
(1, 2,   8, TRUE),   -- Dishes (OK)
(1, 3,   6, TRUE),   -- Bins (quick)
(1, 4,  12, TRUE),   -- Bathroom
(1, 5,   6, TRUE),   -- Kitchen (likes)
(1, 6,  11, TRUE),   -- Laundry
(1, 7,   9, TRUE),   -- Shopping
(1, 8,  14, TRUE),   -- Mopping (dislikes)
(1, 9,   8, TRUE),   -- Dusting
(1, 10, 12, TRUE),   -- Oven cleaning

-- Jordan: prefers light tasks, dislikes laundry & heavy lifting
(2, 1,  11, TRUE),   -- Vacuuming
(2, 2,   9, TRUE),   -- Dishes (OK)
(2, 3,   5, TRUE),   -- Bins (quick)
(2, 4,   8, TRUE),   -- Bathroom
(2, 5,   9, TRUE),   -- Kitchen
(2, 6,  14, TRUE),   -- Laundry (dislikes)
(2, 7,  10, TRUE),   -- Shopping
(2, 8,  12, TRUE),   -- Mopping (dislikes)
(2, 9,   6, TRUE),   -- Dusting (prefers)
(2, 10, 16, TRUE),   -- Oven cleaning

-- Sam: prefers outdoor/shopping, dislikes bathroom & kitchen
(3, 1,   9, TRUE),   -- Vacuuming (OK)
(3, 2,  10, TRUE),   -- Dishes
(3, 3,   5, TRUE),   -- Bins (outdoor, likes)
(3, 4,  14, TRUE),   -- Bathroom (dislikes)
(3, 5,  13, TRUE),   -- Kitchen (dislikes)
(3, 6,   9, TRUE),   -- Laundry
(3, 7,   6, TRUE),   -- Shopping (has car, likes)
(3, 8,   9, TRUE),   -- Mopping
(3, 9,   8, TRUE),   -- Dusting
(3, 10, 17, TRUE),   -- Oven cleaning

-- Taylor: prefers dusting/light work, dislikes dishes & oven, CANNOT do shopping
(4, 1,  12, TRUE),   -- Vacuuming
(4, 2,  13, TRUE),   -- Dishes (dislikes)
(4, 3,   6, TRUE),   -- Bins
(4, 4,  10, TRUE),   -- Bathroom
(4, 5,  11, TRUE),   -- Kitchen
(4, 6,   9, TRUE),   -- Laundry
(4, 7,  15, FALSE),  -- Shopping: CANNOT (no car)
(4, 8,   9, TRUE),   -- Mopping
(4, 9,   5, TRUE),   -- Dusting (prefers light)
(4, 10, 10, TRUE);   -- Oven cleaning (dislikes)


-- ═══════════════════════════════════════════════════════════════════════
--  Household 2 — "The Smiths" (couple, 6 chores)
-- ═══════════════════════════════════════════════════════════════════════

INSERT INTO households (id, name, join_code, admin_id) VALUES (2, 'The Smiths', 'SMITHS', 5);

INSERT INTO household_members (household_id, user_id) VALUES
(2, 5), (2, 6);

INSERT INTO chores (id, household_id, title, is_active) VALUES
(11, 2, 'Dishes',    TRUE),
(12, 2, 'Cooking',   TRUE),
(13, 2, 'Vacuuming', TRUE),
(14, 2, 'Bathroom',  TRUE),
(15, 2, 'Shopping',  TRUE),
(16, 2, 'Laundry',   TRUE);

-- Pat: likes cooking, hates bathroom
INSERT INTO burden_scores (user_id, chore_id, score, is_capable) VALUES
(5, 11, 15, TRUE),   -- Dishes
(5, 12,  8, TRUE),   -- Cooking (doesn't mind)
(5, 13, 12, TRUE),   -- Vacuuming
(5, 14, 30, TRUE),   -- Bathroom (hates)
(5, 15, 15, TRUE),   -- Shopping
(5, 16, 20, TRUE),   -- Laundry

-- Robin: likes vacuuming, hates cooking & shopping
(6, 11, 10, TRUE),   -- Dishes
(6, 12, 25, TRUE),   -- Cooking (hates)
(6, 13,  8, TRUE),   -- Vacuuming (doesn't mind)
(6, 14, 12, TRUE),   -- Bathroom
(6, 15, 30, TRUE),   -- Shopping (hates, works long hours)
(6, 16, 15, TRUE);   -- Laundry


-- ═══════════════════════════════════════════════════════════════════════
--  Household 3 — "Family Home" (2 parents + 2 teens, 8 chores)
-- ═══════════════════════════════════════════════════════════════════════

INSERT INTO households (id, name, join_code, admin_id) VALUES (3, 'Family Home', 'FAMILY', 7);

INSERT INTO household_members (household_id, user_id) VALUES
(3, 7), (3, 8), (3, 9), (3, 10);

INSERT INTO chores (id, household_id, title, is_active) VALUES
(21, 3, 'Dishes',    TRUE),
(22, 3, 'Cooking',   TRUE),
(23, 3, 'Vacuuming', TRUE),
(24, 3, 'Bathroom',  TRUE),
(25, 3, 'Bins',      TRUE),
(26, 3, 'Laundry',   TRUE),
(27, 3, 'Shopping',  TRUE),
(28, 3, 'Tidying',   TRUE);

-- Mum: doesn't mind cooking, hates tidying after teens
INSERT INTO burden_scores (user_id, chore_id, score, is_capable) VALUES
(7, 21, 10, TRUE),
(7, 22,  8, TRUE),   -- Cooking: doesn't mind
(7, 23, 15, TRUE),
(7, 24, 12, TRUE),
(7, 25,  5, TRUE),
(7, 26, 15, TRUE),
(7, 27, 15, TRUE),
(7, 28, 20, TRUE),   -- Tidying: hates cleaning up after teens

-- Dad: outdoor tasks fine, hates laundry
(8, 21, 12, TRUE),
(8, 22, 15, TRUE),
(8, 23, 10, TRUE),
(8, 24, 10, TRUE),
(8, 25,  5, TRUE),   -- Bins: easy
(8, 26, 22, TRUE),   -- Laundry: hates it
(8, 27,  8, TRUE),   -- Shopping: doesn't mind
(8, 28, 18, TRUE),

-- Teen1: avoids everything, especially bathroom; CANNOT shop (no car)
(9, 21, 15, TRUE),
(9, 22, 20, TRUE),
(9, 23, 10, TRUE),
(9, 24, 25, TRUE),   -- Bathroom: absolutely hates
(9, 25,  5, TRUE),
(9, 26, 10, TRUE),
(9, 27, 10, FALSE),  -- Shopping: CANNOT (no car/too young)
(9, 28,  5, TRUE),

-- Teen2: fine with light tasks, CANNOT cook or shop
(10, 21,  8, TRUE),
(10, 22, 20, FALSE), -- Cooking: CANNOT (too young for oven)
(10, 23, 12, TRUE),
(10, 24, 18, TRUE),
(10, 25,  5, TRUE),
(10, 26, 15, TRUE),
(10, 27, 15, FALSE), -- Shopping: CANNOT (too young)
(10, 28,  7, TRUE);

SELECT setval('households_id_seq', 3);
SELECT setval('chores_id_seq', 28);

-- ═══════════════════════════════════════════════════════════════════════
--  INACTIVE DEMO CHORE LIBRARY  (per household)
--  Each chore is is_active=FALSE and pre-seeded with scores for every member.
--  Admin activates them one click at a time from Manage → All Chores.
--  Once active, they can be allocated immediately — no member has to re-rate.
--  Names are intentionally generic and reusable so demo runs feel realistic.
--  In the new "one-shot" allocation model each chore is allocated exactly
--  once, so this library gives the admin enough vocabulary to drive several
--  back-to-back allocation rounds during a demo.
-- ═══════════════════════════════════════════════════════════════════════

-- ── Flat 42 (household 1, members 1-4) ──────────────────────────────────
INSERT INTO chores (id, household_id, title, is_active) VALUES
(29, 1, 'Window cleaning',   FALSE),
(30, 1, 'Fridge cleanout',   FALSE),
(31, 1, 'Garden tidying',    FALSE),
(32, 1, 'Car washing',       FALSE),
(33, 1, 'Mopping floors',    FALSE),
(34, 1, 'Dusting shelves',   FALSE),
(35, 1, 'Watering plants',   FALSE),
(36, 1, 'Sorting recycling', FALSE),
(37, 1, 'Cleaning toilet',   FALSE),
(38, 1, 'Microwave clean',   FALSE),
(39, 1, 'Hallway sweep',     FALSE),
(40, 1, 'Stairs vacuum',     FALSE),
(41, 1, 'Mirror polish',     FALSE),
(42, 1, 'Bin run',           FALSE),
(43, 1, 'Pantry tidy',       FALSE),
(44, 1, 'Light bulb change', FALSE),
(45, 1, 'Plant repot',       FALSE),
(46, 1, 'Drain clear',       FALSE);

INSERT INTO burden_scores (user_id, chore_id, score, is_capable) VALUES
-- Alex (1): hates physical/outdoor, OK with light tidy
(1, 29, 14, TRUE), (1, 30,  8, TRUE), (1, 31, 10, TRUE), (1, 32,  9, TRUE),
(1, 33, 13, TRUE), (1, 34,  7, TRUE), (1, 35,  6, TRUE), (1, 36,  8, TRUE),
(1, 37, 12, TRUE), (1, 38,  7, TRUE), (1, 39,  9, TRUE), (1, 40, 13, TRUE),
(1, 41,  6, TRUE), (1, 42,  8, TRUE), (1, 43,  7, TRUE), (1, 44,  5, TRUE),
(1, 45,  8, TRUE), (1, 46, 14, TRUE),
-- Jordan (2): dislikes outdoor + heavy stuff, fine indoor
(2, 29, 10, TRUE), (2, 30,  8, TRUE), (2, 31, 14, TRUE), (2, 32, 13, TRUE),
(2, 33, 11, TRUE), (2, 34,  6, TRUE), (2, 35,  7, TRUE), (2, 36,  9, TRUE),
(2, 37, 11, TRUE), (2, 38,  6, TRUE), (2, 39,  8, TRUE), (2, 40, 12, TRUE),
(2, 41,  6, TRUE), (2, 42,  8, TRUE), (2, 43,  7, TRUE), (2, 44,  6, TRUE),
(2, 45,  9, TRUE), (2, 46, 13, TRUE),
-- Sam (3): likes outdoor & physical, dislikes detailed cleaning
(3, 29, 13, TRUE), (3, 30, 10, TRUE), (3, 31,  6, TRUE), (3, 32,  8, TRUE),
(3, 33, 10, TRUE), (3, 34, 11, TRUE), (3, 35,  7, TRUE), (3, 36,  6, TRUE),
(3, 37, 14, TRUE), (3, 38, 10, TRUE), (3, 39,  8, TRUE), (3, 40, 11, TRUE),
(3, 41, 12, TRUE), (3, 42,  6, TRUE), (3, 43, 10, TRUE), (3, 44,  6, TRUE),
(3, 45,  7, TRUE), (3, 46,  9, TRUE),
-- Taylor (4): CANNOT garden, CANNOT car (incapable rows). Likes light tidy.
(4, 29, 11, TRUE), (4, 30,  9, TRUE), (4, 31, 15, FALSE), (4, 32, 12, FALSE),
(4, 33, 12, TRUE), (4, 34,  6, TRUE), (4, 35,  6, TRUE), (4, 36,  8, TRUE),
(4, 37, 10, TRUE), (4, 38,  7, TRUE), (4, 39,  9, TRUE), (4, 40, 12, TRUE),
(4, 41,  6, TRUE), (4, 42,  9, TRUE), (4, 43,  7, TRUE), (4, 44,  6, TRUE),
(4, 45, 10, TRUE), (4, 46, 15, FALSE);

-- ── The Smiths (household 2, members 5-6) ───────────────────────────────
INSERT INTO chores (id, household_id, title, is_active) VALUES
(47, 2, 'Window cleaning',   FALSE),
(48, 2, 'Fridge cleanout',   FALSE),
(49, 2, 'Mopping floors',    FALSE),
(50, 2, 'Watering plants',   FALSE),
(51, 2, 'Cleaning toilet',   FALSE),
(52, 2, 'Bin run',           FALSE),
(53, 2, 'Microwave clean',   FALSE),
(54, 2, 'Pantry tidy',       FALSE),
(55, 2, 'Mirror polish',     FALSE),
(56, 2, 'Sorting recycling', FALSE),
(57, 2, 'Hallway sweep',     FALSE),
(58, 2, 'Light bulb change', FALSE),
(59, 2, 'Drain clear',       FALSE),
(60, 2, 'Linen change',      FALSE),
(61, 2, 'Oven cleaning',     FALSE);

INSERT INTO burden_scores (user_id, chore_id, score, is_capable) VALUES
-- Pat (5): hates bathroom-y things, fine cooking-adjacent
(5, 47, 14, TRUE), (5, 48,  8, TRUE), (5, 49, 13, TRUE), (5, 50,  6, TRUE),
(5, 51, 16, TRUE), (5, 52,  7, TRUE), (5, 53,  8, TRUE), (5, 54,  8, TRUE),
(5, 55,  7, TRUE), (5, 56,  9, TRUE), (5, 57,  9, TRUE), (5, 58,  6, TRUE),
(5, 59, 14, TRUE), (5, 60, 12, TRUE), (5, 61, 15, TRUE),
-- Robin (6): hates kitchen detail, fine bathroom-y
(6, 47, 12, TRUE), (6, 48, 11, TRUE), (6, 49, 10, TRUE), (6, 50,  7, TRUE),
(6, 51, 11, TRUE), (6, 52,  6, TRUE), (6, 53, 12, TRUE), (6, 54, 10, TRUE),
(6, 55,  8, TRUE), (6, 56,  6, TRUE), (6, 57,  8, TRUE), (6, 58,  6, TRUE),
(6, 59, 12, TRUE), (6, 60, 11, TRUE), (6, 61, 18, TRUE);

-- ── Family Home (household 3, members 7-10) ─────────────────────────────
INSERT INTO chores (id, household_id, title, is_active) VALUES
(62, 3, 'Window cleaning',   FALSE),
(63, 3, 'Fridge cleanout',   FALSE),
(64, 3, 'Garden tidying',    FALSE),
(65, 3, 'Mopping floors',    FALSE),
(66, 3, 'Watering plants',   FALSE),
(67, 3, 'Cleaning toilet',   FALSE),
(68, 3, 'Bin run',           FALSE),
(69, 3, 'Microwave clean',   FALSE),
(70, 3, 'Pantry tidy',       FALSE),
(71, 3, 'Sorting recycling', FALSE),
(72, 3, 'Hallway sweep',     FALSE),
(73, 3, 'Light bulb change', FALSE),
(74, 3, 'Drain clear',       FALSE),
(75, 3, 'Linen change',      FALSE),
(76, 3, 'Stairs vacuum',     FALSE);

INSERT INTO burden_scores (user_id, chore_id, score, is_capable) VALUES
-- Mum (7): low-stress on cooking-adjacent and tidy-up
(7, 62, 13, TRUE), (7, 63,  9, TRUE), (7, 64, 11, TRUE), (7, 65, 12, TRUE),
(7, 66,  6, TRUE), (7, 67, 12, TRUE), (7, 68,  6, TRUE), (7, 69,  7, TRUE),
(7, 70,  8, TRUE), (7, 71,  9, TRUE), (7, 72,  9, TRUE), (7, 73,  6, TRUE),
(7, 74, 13, TRUE), (7, 75, 10, TRUE), (7, 76, 12, TRUE),
-- Dad (8): outdoor & physical fine, hates linen / fiddly
(8, 62, 11, TRUE), (8, 63, 12, TRUE), (8, 64,  7, TRUE), (8, 65, 10, TRUE),
(8, 66,  7, TRUE), (8, 67, 11, TRUE), (8, 68,  6, TRUE), (8, 69, 11, TRUE),
(8, 70, 11, TRUE), (8, 71,  8, TRUE), (8, 72,  8, TRUE), (8, 73,  6, TRUE),
(8, 74, 10, TRUE), (8, 75, 16, TRUE), (8, 76, 11, TRUE),
-- Teen1 (9): avoids bathroom & detailed work; can do most physical
(9, 62, 14, TRUE), (9, 63, 12, TRUE), (9, 64,  9, TRUE), (9, 65, 11, TRUE),
(9, 66,  6, TRUE), (9, 67, 18, TRUE), (9, 68,  6, TRUE), (9, 69,  9, TRUE),
(9, 70, 10, TRUE), (9, 71,  7, TRUE), (9, 72,  9, TRUE), (9, 73,  9, TRUE),
(9, 74, 13, TRUE), (9, 75, 11, TRUE), (9, 76, 10, TRUE),
-- Teen2 (10): CANNOT garden (too young), CANNOT drain (no skill); light tasks fine
(10, 62, 12, TRUE),  (10, 63, 10, TRUE),  (10, 64, 14, FALSE),
(10, 65, 11, TRUE),  (10, 66,  6, TRUE),  (10, 67, 14, TRUE),
(10, 68,  6, TRUE),  (10, 69,  8, TRUE),  (10, 70,  9, TRUE),
(10, 71,  7, TRUE),  (10, 72,  9, TRUE),  (10, 73, 10, TRUE),
(10, 74, 16, FALSE), (10, 75, 12, TRUE),  (10, 76, 11, TRUE);

SELECT setval('chores_id_seq', 76);

-- ═══════════════════════════════════════════════════════════════════════
--  DEMO REALISM: clear ALL admin scores so they start unrated.
--  Admin users (1=Alex/Flat42, 5=Pat/Smiths, 7=Mum/Family) must rate
--  every chore via the Preferences screen during the demo. The other
--  household members keep their pre-seeded scores so allocations can
--  still run as soon as the admin finishes rating.
-- ═══════════════════════════════════════════════════════════════════════
DELETE FROM burden_scores WHERE user_id IN (1, 5, 7);
