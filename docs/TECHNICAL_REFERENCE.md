# FairChore — Full Project Context

**Student:** Abdulmalik Alqahtani | **Supervisor:** Dr. Bahar Rastegari
**Degree:** BEng Software Engineering, University of Southampton
**Module:** COMP3200 Part III Individual Project

This document is the canonical reference for theory, design, implementation, testing, and evaluation — intended to feed a report-writing assistant with accurate, up-to-date project context.

---

## 1. Project Overview

FairChore is a full-stack web application that allocates household chores fairly using academic fair-division algorithms for **chores** (disutility items), not goods.

**Tech stack**
- Backend: Python 3, Flask, psycopg2 (PostgreSQL driver), custom HS256 JWT auth
- Database: PostgreSQL 14+
- Frontend: React 18 (Create React App), single-file app `frontend/src/App.jsx`
- Dev: backend on `:5000`, frontend on `:3000` (proxied to `:5000`)
- Start backend: `venv/Scripts/python backend/app.py`
- Start frontend: `cd frontend && npm start`
- Reset DB: `python scripts/reset_db.py --yes` (drops + re-seeds from `schema.sql`)

**Conceptual positioning**
- Chore allocation ≠ goods allocation. Costs (disutility) flip the direction of envy and MMS, so standard Lipton-style envy-cycle elimination does not work.
- FairChore implements three provably fair algorithms for chores: Greedy Round-Robin (Aziz et al. 2017), Bag-Filling with ordinal MMS (Hosseini et al. 2022), and Top-Trading Envy-Cycle (Bhaskar et al. 2021).
- All algorithms are pure Python functions, decoupled from the web stack, so the same implementation is evaluated offline in `evaluation/` and called online by the backend.

---

## 2. Preference (Burden) Model

### 2.1 What scores represent

`scores[member][chore]` is a **positive integer disutility**. Higher = hates the chore more. Each member's scores sum to ~100 (a fixed budget that prevents strategic gaming).

These are stored in the `burden_scores` table (previously `effort_scores`); the word *burden* is used consistently throughout the UI, API and schema.

### 2.2 Frontend rating UI

The user never types numbers. They select one of four emoji ratings per chore:

| Rating | Emoji | Meaning           | Cost weight |
|--------|-------|-------------------|-------------|
| 1      | 😊    | Fine              | 3           |
| 2      | 🙂    | Neutral           | 4           |
| 3      | 😕    | Don't like        | 5           |
| 4      | 😤    | Strongly dislike  | 6           |

`RATING_COSTS = {1: 3, 2: 4, 3: 5, 4: 6}` (see `backend/app.py`).

Two rating-distribution constraints prevent the degenerate "everything is terrible" pattern:
- **Tier 1:** at most `max(1, m//3)` chores may be rated 😤
- **Tier 2:** at most `max(2, 2m//3)` chores may be rated 😕 or 😤 combined

where `m` = number of chores being rated. These caps only apply when m ≥ 3.

### 2.3 Normalisation to 100-sum

On save, the backend normalises each member's rated chores to a 100-point budget:

```python
cost[c]  = RATING_COSTS[rating[c]]
score[c] = round(cost[c] * 100 / sum(cost.values()))
# rounding residual assigned to highest-scoring chore so the sum is exactly 100
```

### 2.4 Capability flag

Each `(user, chore)` row in `burden_scores` has `is_capable BOOLEAN`. False means the user physically cannot do the chore (no car, too young, allergic…). The algorithms ignore infeasible (member, chore) pairs when choosing.

---

## 3. Algorithms

All algorithms are pure functions in `algorithms/` with a shared signature:

```python
def algorithm(scores, capable=None):
    """
    scores  : dict[member][chore] = int  (higher = more disutility)
    capable : dict[member][chore] = bool (optional; default everyone-capable)
    returns : dict[member] = list[chore]  (every chore once; every member keyed)
    """
```

The backend composes them with historical data (see §5.5) but the algorithm itself has no dependency on the database.

### 3.1 Greedy Round-Robin

**File:** `algorithms/round_robin.py` — `greedy_round_robin`
**Reference:** Aziz, Rauchecker, Schryen, Walsh (AAAI 2017), Theorem 9

1. Members cycle in list order (backend pre-sorts by total-burden ASC so under-burdened members pick first).
2. On each turn the current member picks the **feasible** chore with the lowest score.
3. If no feasible chore is available for the current member, their turn is skipped.
4. Continue until all chores assigned.

**Guarantee:** EF1 for unconstrained preferences. Capability constraints may break EF1.
**Complexity:** `O(nm log m)`.

### 3.2 Bag-Filling

**File:** `algorithms/bag_filling.py` — `bag_filling(scores, capable, variant="paper"|"practical")`
**Reference:** Hosseini, Searns, Segal-Halevi (AAMAS 2022), Theorem 4.1

1. Compute a per-member **threshold** = the maximum bundle burden they will accept.
2. Sort chores by household-average score **descending** (hardest first).
3. Fill a bag chore-by-chore while at least one member can accept the enlarged bag (burden ≤ their threshold AND feasible). Assign the bag to that member; remove them and the bag's chores.
4. Last member receives any remaining chores.

**Threshold formula** (differs only in `d`):
```
threshold = max(
    s[0],
    s[d-1] + s[d],
    s[2d-2] + s[2d-1] + s[2d],
    total / d
)
```
`s[i]` is the member's `i`-th hardest chore (0 if out of range).
- `variant="paper"` uses `d = ⌊2n/3⌋` — matches the AAMAS 2022 proof but degenerates for small households.
- `variant="practical"` uses `d = n` (proportional share) — original contribution; much better EF1 and MMS on n=2..4.

**Complexity:** `O(n²m)`.

### 3.3 Top-Trading Envy-Cycle Elimination

**File:** `algorithms/top_trading.py` — `top_trading_envy_cycle`
**Reference:** Bhaskar, Sricharan, Vaish (APPROX/RANDOM 2021)

Standard Lipton (2004) envy-cycle elimination works for goods and fails for chores. Bhaskar et al. invert the direction: each agent points to whoever holds the bundle they'd most *prefer* (lowest burden).

1. Sort chores by household-average score descending.
2. For each chore to assign:
   a. Build the top-trading graph: edge from `i` to `j` iff `burden_i(bundle_j) < burden_i(bundle_i)`. Infeasible bundles have `+∞` burden.
   b. While the graph has a cycle, rotate bundles along it and rebuild.
   c. Take a sink (no outgoing edge). Among *feasible* sinks pick the one who minds this chore least. Append the chore to their bundle.
3. Return.

**Guarantee:** EF1. **Complexity:** `O(n²m)`.

### 3.4 Baselines

`random_allocation`, `rotation_allocation` in `algorithms/baselines.py` — used only for comparison in the evaluation. Not exposed in the UI.

---

## 4. Fairness Metrics

**File:** `algorithms/metrics.py`
**Entry point:** `compute_all_metrics(scores, allocation)` → dict

```python
{
  "ef1": bool,
  "ef1_violation_count": int,
  "max_envy": float,
  "workload_ratio": float,   # max_burden / min_burden
  "workload_std": float,
  "worst_mms_ratio": float,  # max(actual / MMS)
  "zero_chore_members": int,
  "all_assigned": bool,
  "burden_min" / "burden_max" / "burden_mean": float,
}
```

Individual functions:
- `check_ef1(scores, allocation)` — EF1 for chores: `i` envies `j` iff `i`'s burden on their own bundle > `i`'s burden on `j`'s bundle, and **removing any single chore from i's bundle still leaves i envying j**.
- `compute_max_envy` — scalar "how far from envy-free"
- `compute_workload_balance` — min/max/mean/ratio/std/burdens
- `compute_mms_exact` — brute-force MaxiMin Share (falls back to greedy approximation for `chores > 8` or `members > 3`)
- `zero_chore_count` — count of members with empty bundles

Metrics are computed on **raw preference scores**, not on the adjusted (history-weighted) scores that drive the algorithm — this gives an honest picture of realised fairness.

---

## 5. Backend API

**File:** `backend/app.py`. Flask app on port 5000. CORS: origins from `ALLOWED_ORIGINS` env var (default `http://localhost:3000`).

### 5.1 Auth

- Custom JWT (HS256). Payload: `{sub: user_id, username, exp}`. 7-day expiry.
- Passwords: PBKDF2-HMAC-SHA256, 260,000 iterations, 16-byte hex salt. Stored as `salt:hash`.
- `@require_auth` decorator parses `Authorization: Bearer …`, populates `g.user_id` and `g.username`.
- Join-code neutrality: when a user joins via code, their `total_burden_accumulated` is initialised to the household average so they don't instantly pick first (would otherwise dominate round-robin ordering).

### 5.2 Endpoint list

| Method | Path                                              | Auth          | Purpose |
|--------|---------------------------------------------------|---------------|---------|
| POST   | `/api/register`                                   | —             | `{name,email,password}` → `{token,user}` |
| POST   | `/api/login`                                      | —             | `{email,password}` → `{token,user}` |
| GET    | `/api/me`                                         | user          | current user |
| GET    | `/api/households`                                 | user          | list my households |
| POST   | `/api/households`                                 | user          | create household |
| POST   | `/api/households/join`                            | user          | join by 6-char code |
| GET    | `/api/households/<id>`                            | member        | full household + members + chores (active **and** inactive, with `is_active` flag) |
| PATCH  | `/api/households/<id>/admin`                      | admin         | transfer admin role |
| GET    | `/api/households/<id>/burden-balance`             | member        | daily/weekly/monthly burden per member and `% of fair share` |
| POST   | `/api/households/<id>/chores`                     | admin         | add chore; creates burden_scores row (`score=0`, default `is_capable=True`) for every member |
| DELETE | `/api/chores/<id>`                                | admin         | soft-delete (`is_active=FALSE`) |
| PATCH  | `/api/chores/<id>/activate`                       | admin         | reactivate |
| POST   | `/api/households/<id>/preferences`                | member        | `{ratings:{chore_id:1..4}}` or legacy `{scores:…}` — normalised to 100-sum |
| GET    | `/api/households/<id>/my-preferences`             | member        | `{chore_id:{score,is_capable}}` (active chores only) |
| GET    | `/api/households/<id>/preferences-ready`          | member        | `[{id,name,ready,unassigned_total,unrated}]` — ready means all **unassigned** active chores are rated |
| POST   | `/api/households/<id>/allocate`                   | admin         | **dry run** — computes allocation over unassigned chores only; saves nothing |
| POST   | `/api/households/<id>/allocate/confirm`           | admin         | persists the dry-run result + scores + metrics |
| POST   | `/api/assignments/<id>/complete`                  | assignee only | mark chore done (`completed_at = NOW()`) |
| DELETE | `/api/assignments/<id>/complete`                  | assignee only | undo completion |
| GET    | `/api/households/<id>/history`                    | member        | last 20 rounds with `assignment_id`, `completed_at`, stored `scores`/`metrics` |
| GET    | `/api/households/<id>/contributions`              | member        | cumulative `total_burden`, `%` vs fair share |
| POST   | `/api/allocate-json`                              | —             | stateless testing endpoint (no DB, no auth) |
| PATCH  | `/api/account`                                    | user          | update name/email |
| DELETE | `/api/account`                                    | user          | delete account (cascades) |

### 5.3 Two-phase allocation flow

The UI never commits an allocation the user has not seen.

1. **`POST /allocate`** — the admin asks for a preview:
   - Fetches **unassigned** chores only: a chore is "assigned" if *any* `assignment_history` row for it has `completed_at IS NULL`. Chores already in-progress in a prior cycle are excluded so the algorithm never reassigns active work.
   - Enforces that every member has rated every active chore (`score > 0`). If not, returns 400 with a list of missing ratings.
   - Sorts members by `total_burden_accumulated ASC` (temporal reciprocity — the least-burdened picks first).
   - Computes historical load (see §5.5) and **AdjustedScore = preference + λ × HistoricalLoad** with `λ = 0.3`.
   - Runs the chosen algorithm on adjusted scores (except bag-filling, which needs the 100-sum raw scores for its thresholds).
   - Post-processes any member left with zero chores: donate one chore from the most-loaded member, respecting capabilities.
   - Computes metrics on **raw** scores (honest EF1/MMS reporting).
   - Returns `{algorithm, allocation[], metrics, scores, explanation}`. Nothing is written to the database.

2. **`POST /allocate/confirm`** — the admin approves the preview:
   - Receives the preview back (`allocation`, `algorithm`, `scores`, `metrics`).
   - Generates one `confirmed_at = datetime.utcnow()` shared by **all** inserts in this batch — this timestamp identifies the round.
   - Inserts one `assignment_history` row per (member, chore) with that `confirmed_at`, `burden_at_time` = household-average burden for that chore at the time of allocation (dry run computed this via `ROUND(AVG(score)::numeric, 2)` over `score > 0` rows), and `completed_at = NULL`.
   - Increments `users.total_burden_accumulated` by the member's burden sum.
   - Inserts one row into `allocation_results` (`round_ts` = `confirmed_at`) with the full scores matrix (`scores_json`) and metrics (`metrics_json`) so the round can be replayed verbatim on a "Past allocation" view.

### 5.4 Cycle model

"Cycle" is the user-facing name for an allocation round. FairChore does not have fixed-length cycles; cycles overlap naturally because undone chores persist until marked done.

- `assignment_history.completed_at` is the single source of truth for done/undone state.
- *Current cycle* for a user = the latest round (by `date_assigned DESC`) that contains them.
- *Overdue from cycle N* = a chore from any older round whose `completed_at IS NULL` — these are displayed on the user's "My Chores" view with a warning label so they don't vanish silently.
- When a cycle's chores are all completed, preferences can change and a fresh allocation runs against the next unassigned pool.

### 5.5 Historical load (temporal reciprocity)

`compute_historical_burdens(cur, house_id, member_ids)` returns each member's load normalised to a 0–5 scale (household average → 2.5):

```
raw(uid)        = 0.2 × daily + 0.5 × weekly + 0.3 × monthly      # sums of burden_at_time
avg             = mean(raw values across members)
load_norm(uid)  = round(raw(uid) / avg × 2.5, 2)
```

Windows: `daily = today`, `weekly = last 7 days`, `monthly = last 30 days` (date_assigned >= start).

This is combined with the current preferences into an adjusted score:
```
pref_on_5(uid, c)     = clamp(score / (100/n_chores) × 2.5, 1, 5)
adjusted[uid][c]      = pref_on_5 + λ × load_norm(uid)    # λ = 0.3
```

Round-Robin and Top-Trading consume the adjusted scores so the more historically-burdened a member is, the more reluctant they appear, and the earlier their turn comes. Bag-Filling's thresholds are calibrated to a 100-sum budget, so it uses the **raw** scores.

### 5.6 Allocation response shape

```jsonc
{
  "algorithm": "top-trading",
  "allocation": [
    {
      "member": "Alex", "member_id": 1,
      "chores": [
        {"id": 2, "title": "Dishes", "burden_at_time": 9.5}
      ],
      "burden": 9.5,             // sum of burden_at_time (household average)
      "perceived_burden": 8,     // sum of this member's own preference score
      "adjusted_burden": 4.23,   // sum of adjusted scores (1–5 + λ×hist)
      "past_burden": 120.0,      // total_burden_accumulated before this round
      "chore_count": 1
    }
  ],
  "metrics": { /* see §4 */ },
  "scores": { "Alex": { "Dishes": 8, … }, … },
  "explanation": "Top-Trading: …"
}
```

`burden` is now the household-average sum (matches the home screen's burden-balance metric, so percentages line up between screens). `perceived_burden` is kept alongside for explanations ("*you* got this because *you* mind it least").

### 5.7 Stateless testing endpoint

`POST /api/allocate-json` runs any algorithm directly from a JSON body (`members`, `chores`, `scores`, optional `capabilities`). No auth, no DB. Useful for demos and the integration test harness.

---

## 6. Database Schema

`schema.sql` is the single source of truth. Reset with `python scripts/reset_db.py --yes`.

```sql
users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100),
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(512),               -- "salt_hex:pbkdf2_hex"
    total_burden_accumulated NUMERIC(12,2) DEFAULT 0,
    created_at TIMESTAMP
)

households (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    join_code VARCHAR(10) UNIQUE,             -- 6-char alphanumeric
    admin_id INTEGER REFERENCES users,
    created_at TIMESTAMP
)

household_members (
    household_id INTEGER REFERENCES households ON DELETE CASCADE,
    user_id      INTEGER REFERENCES users      ON DELETE CASCADE,
    PRIMARY KEY (household_id, user_id)
)

chores (
    id SERIAL PRIMARY KEY,
    household_id INTEGER REFERENCES households ON DELETE CASCADE,
    title VARCHAR(255),
    description TEXT DEFAULT '',
    is_active BOOLEAN DEFAULT TRUE,           -- soft-delete flag
    created_at TIMESTAMP
)

burden_scores (                               -- preference matrix
    id SERIAL PRIMARY KEY,
    user_id  INTEGER REFERENCES users  ON DELETE CASCADE,
    chore_id INTEGER REFERENCES chores ON DELETE CASCADE,
    score    INTEGER DEFAULT 0,               -- normalised 100-sum
    is_capable BOOLEAN DEFAULT TRUE,
    UNIQUE(user_id, chore_id)
)

assignment_history (
    id SERIAL PRIMARY KEY,
    user_id  INTEGER REFERENCES users,
    chore_id INTEGER REFERENCES chores,
    burden_at_time NUMERIC(10,2),             -- household-average burden snapshot
    algorithm_used VARCHAR(50),
    date_assigned  TIMESTAMP DEFAULT NOW(),   -- shared across a batch = one round
    completed_at   TIMESTAMP NULL DEFAULT NULL
)

allocation_results (                          -- full scores matrix + metrics per round
    id SERIAL PRIMARY KEY,
    household_id INTEGER REFERENCES households ON DELETE CASCADE,
    round_ts TIMESTAMP UNIQUE NOT NULL,       -- == assignment_history.date_assigned
    algorithm VARCHAR(50),
    scores_json  JSONB NOT NULL DEFAULT '{}',
    metrics_json JSONB NOT NULL DEFAULT '{}'
)
```

**Seed data** — three demo households, all admin passwords `test123`:

| Household    | Join code | Admin  | Members                        | Active chores | Inactive pool | Notes |
|--------------|-----------|--------|--------------------------------|---------------|----------------|-------|
| Flat 42      | `FLAT42`  | Alex   | Alex, Jordan, Sam, Taylor      | 10            | 4 (Window cleaning, Fridge cleanout, Garden tidying, Car washing) | Taylor can't shop; can't garden or wash car |
| The Smiths   | `SMITHS`  | Pat    | Pat, Robin                     | 6             | 0              | Opposite preferences |
| Family Home  | `FAMILY`  | Mum    | Mum, Dad, Teen1, Teen2         | 8             | 0              | Teens blocked from shopping/cooking |

The four inactive Flat 42 chores are pre-seeded with preferences for every member; the admin can Activate them from the Chores → All Chores → Manage screen to exercise the "new chore added mid-cycle" path without re-entering preferences.

---

## 7. Frontend

**Directory:** `frontend/`. Single source file `src/App.jsx` (~2.5k lines), single stylesheet `src/App.css`. No router — a `screen` state variable controls which component renders. No component library.

### 7.1 Persistent state

- `fairchore_auth` (localStorage): `{token, user}`. Restored on mount; cleared on any 401.
- **No** localStorage for done-state any more — done/undone is a server field (`completed_at`) authored only by the assignee.
- No per-household allocation cache — the server `/history` endpoint is the source of truth.

### 7.2 Screen map

```
welcome → login / register → home
home ↔ preferences          (rate unassigned chores)
home ↔ chores               (My Chores / All Chores tabs)
home ↔ add-chore            (admin)
home ↔ allocate             (admin; dry-run → confirm)
home ↔ results              (fresh or historical view)
home ↔ settings             (household, switch household, admin transfer, account)
home ↔ join / create        (household management)
```

### 7.3 Key behaviours

**PreferencesScreen** — renders only chores that are **active and unassigned** (filtered against `allocHistory` rows with `completed_at IS NULL`). The 100-point budget bar + the two rating-tier caps prevent degenerate inputs. Reverse-engineers the stored normalised score back to a 1..4 rating on load.

**AllocateScreen** — step 1 admin runs `POST /allocate` and sees the preview; step 2 clicks "Confirm" to `POST /allocate/confirm`. Blocked if any member isn't ready.

**ResultsScreen** — renders the preview response or a historical round (from `/history`, which now stores the full scores matrix so past rounds show the same comparison UI). Burden bars use the household-average `burden` field so percentages agree with the home screen. Badges:
- `pct ≤ 125%` → *Fair share* (green)
- `pct ≤ 160%` → *Slightly above* (amber)
- `pct > 160%` → *Above fair share* (red)

**ChoresScreen**
- *My Chores* tab lists every cycle containing the current user, newest first, with date label; past-cycle chores that remain undone are re-surfaced with an "Overdue from cycle N" label. Done/undo toggle calls `POST|DELETE /api/assignments/<id>/complete`.
- *All Chores* tab shows every household member with their current-cycle chores plus any of their overdue items. Read-only for everyone except the assignee.
- *Manage* view (admin) lists inactive chores with an Activate button.

**HomeScreen** — greeting, burden-balance bar chart with daily/weekly/monthly toggle, contextual CTAs (set preferences / run allocation / view chores), "Your chores this cycle" from the latest round in `/history`.

### 7.4 API plumbing

All calls go through `apiFetch(path, opts, onUnauth)` which injects the bearer token and handles 401 globally. `package.json` has `"proxy": "http://localhost:5000"` so unprefixed `/api/...` requests route to the backend in development.

---

## 8. Evaluation and Simulation

### 8.1 Code

- `simulation/personas.py` — 25-chore pool, 12 persona templates, 17 scenarios, score generators
- `evaluation/run_simulation.py` — runs every (scenario × scoring × run × algorithm) combination, writes `results/summary.csv`, renders 6 PNG charts
- Entry: `python scripts/run_eval.py`
- `results/summary.csv` currently has 20,400 rows = 17 × 100 × 2 × 6 (scenarios × runs × scoring methods × algorithms)

### 8.2 Personas

Each persona: `category_weights`, `effort_sensitivity`, `base_burden`, `restricted_mobility`, `age`, `contribution`. Templates include `balanced_adult`, `busy_worker`, `clean_freak`, `bathroom_hater`, `kitchen_lover`, `outdoor_preferer`, `avoidant`, `teenager`, `young_child`, `elderly`, `injured_member`, `exam_period`.

### 8.3 Chore pool

25 chores across kitchen, cooking, cleaning, bathroom, laundry, outdoor, general. Each chore carries `effort` (1–5), `time` (1–5), `min_age`, `mobility` (bool). Note: `effort` *here* is an intrinsic chore attribute (physical effort to do the chore) — distinct from the user-facing *burden* score stored in the app. The two names intentionally differ so the simulation doesn't conflate the two concepts.

`can_do_chore(persona, chore)` → False if `persona.age < chore.min_age` or `persona.restricted_mobility AND chore.mobility`.

### 8.4 Scoring methods

**Budget (100-sum, matches production):**
```
raw      = (chore.effort + 0.5 × chore.time) × category_weight ×
           effort_sensitivity × base_burden × gaussian_noise(±20%)
score[c] = raw[c] / sum(raw) × 100
```

**Rating (1–10 per chore, for method comparison):** same raw formula scaled to 1..10, no cross-chore normalisation.

### 8.5 Scenarios (17)

- **Small (2–3 members):** equal couple, unequal couple, student flat (3), student flat + freeloader, couple + lodger
- **Medium (4–6 members):** family with young kids, family with teenagers, professional houseshare, mixed houseshare, student house (6)
- **Large (6+ members):** multi-generational family, large houseshare (8), houseshare + injured member, all similar preferences, extreme preference conflict, very large household (10), stress test (15)

### 8.6 Simulation loop

```
for scenario in SCENARIOS:
  for scoring in {budget, rating}:
    for run in 1..100:
      households = generate_scenario(scenario, scoring, seed=run)  # same seed across algorithms
      for algo in {round_robin, bag_paper, bag_practical, top_trading, random, rotation}:
        t0 = time.perf_counter()
        alloc = algo(households.scores, households.capable)
        elapsed = time.perf_counter() - t0
        metrics = compute_all_metrics(households.scores, alloc)
        write row(scenario, scoring, run, algo, elapsed, **metrics)
```

### 8.7 Charts (`results/*.png`)

`ef1_comparison.png`, `workload_balance.png`, `mms_comparison.png`, `runtime_scaling.png`, `budget_vs_rating.png`, `zero_chores.png`.

### 8.8 Headline results (from `summary.csv`, budget scoring)

| Algorithm             | EF1 rate | Avg MMS ratio | Avg workload ratio | Zero-chore members |
|-----------------------|---------:|--------------:|-------------------:|-------------------:|
| Round-Robin           |   ~85%   |     1.07      |       3.74         |      0.01          |
| Bag-Filling Practical |   ~38%   |     **1.02**  |      30.9          |      0.78          |
| Bag-Filling Paper     |    ~0%   |     1.66      |      99.4          |      2.29          |
| Top-Trading           | ~Round-Robin | TBC      | TBC                | TBC                |
| Random                |    ~9%   |     1.71      |      29.1          |      0.38          |
| Rotation              |   ~28%   |     1.42      |      10.7          |      0.09          |

Interpretation: Round-Robin and Top-Trading are the EF1 workhorses; Bag-Filling Practical sacrifices EF1 for near-optimal MMS; Bag-Filling Paper is unusable on small households (`⌊2n/3⌋ = 1` collapses the threshold).

---

## 9. Testing

Runner: `python scripts/run_tests.py` (wraps pytest).

- **tests/unit/test_algorithms.py** — 95+ checks over algorithms, metrics, paper theorems, persona generation
- **tests/integration/test_fairness_over_time.py** — multi-round fairness across household types
- **tests/db/test_schema.py** — table/column existence, unique/cascade constraints, defaults, seed-data integrity (all three households, join codes, score sums = 100, capability flags for Taylor/Teen1/Teen2, no unrated chores)
- **tests/api/test_endpoints.py** — end-to-end flows over the Flask test client against the `fairchore_test` database

The `fairchore_test` DB is created and seeded with a minimal DDL (no seed rows) by `tests/conftest.py::setup_test_database` (session-scoped), truncated before every test by the `clean_tables` autouse fixture, and dropped at session teardown. The production DB is untouched.

---

## 10. Project Layout

```
FairChore/
├── algorithms/             # Pure algorithm + metrics library
│   ├── __init__.py         # exports
│   ├── round_robin.py
│   ├── bag_filling.py
│   ├── top_trading.py
│   ├── baselines.py
│   └── metrics.py
├── simulation/             # Synthetic households + scenarios
│   ├── __init__.py
│   └── personas.py
├── evaluation/
│   └── run_simulation.py
├── backend/
│   └── app.py              # Flask app, JWT, all endpoints
├── frontend/
│   ├── package.json
│   ├── public/index.html
│   └── src/{App.jsx, App.css}
├── scripts/
│   ├── reset_db.py
│   ├── run_tests.py
│   └── run_eval.py
├── tests/
│   ├── conftest.py
│   ├── unit/test_algorithms.py
│   ├── integration/test_fairness_over_time.py
│   ├── db/test_schema.py
│   └── api/test_endpoints.py
├── results/                # generated PNGs + summary.csv
├── docs/
│   ├── ARCHITECTURE.md
│   └── TECHNICAL_REFERENCE.md   # this file
├── schema.sql
├── requirements.txt
└── README.md
```

---

## 11. Component Interaction

```
Browser ── React (port 3000) ── Flask API (port 5000) ── PostgreSQL
                  │                     │
              localStorage            algorithms/, simulation/
              (auth only)             (pure Python, no DB)
```

**Happy-path walk-through**

1. Register → JWT stored in `localStorage`.
2. Create household → 6-char join code. Creator = admin.
3. Other members join by code → `total_burden_accumulated` seeded to household average.
4. Admin adds chores → a `burden_scores` row is inserted for every member with `score = 0` and `is_capable = True` (or overridden via the capabilities payload).
5. Each member rates the unassigned active chores in Preferences → scores are normalised to a 100-sum and stored.
6. `preferences-ready` turns all-green.
7. Admin opens Allocate, picks an algorithm, `POST /allocate` returns a preview. Admin reviews metrics.
8. Admin clicks Confirm → `POST /allocate/confirm` writes `assignment_history` rows (shared `confirmed_at`) and one `allocation_results` row; `total_burden_accumulated` ticks up; UI shows ResultsScreen.
9. Members tick chores done on ChoresScreen → `completed_at` filled. Others see the strike-through but cannot toggle it.
10. Once all chores done (and any new chores activated), next cycle runs against whatever is now unassigned.

---

## 12. Constraints & Non-Obvious Behaviours

1. **Allocations only see unassigned chores.** Chores with an `assignment_history` row whose `completed_at IS NULL` are skipped by `/allocate`, `/preferences-ready`, and the Preferences UI — they're "still in flight".
2. **`burden` on the /allocate response is the household-average sum** (matches `/burden-balance`). The member's own preference sum is `perceived_burden`.
3. **`burden_at_time` is `NUMERIC(10,2)`** — fractional precision matters because it's the average of integer scores.
4. **Bag-Filling "paper" degenerates for n ≤ 3.** The UI exposes only `bag-filling-practical`. The paper variant is retained for the evaluation harness.
5. **Round-Robin turn order is set by the backend**, not the algorithm: members are sorted by `total_burden_accumulated ASC` so the least-loaded picks first (temporal reciprocity).
6. **MMS is approximated for large instances** (`chores > 8` or `members > 3`) — greedy round-robin on sorted chores.
7. **Simulation seeds are shared across algorithms** within a run so comparisons are apples-to-apples.
8. **Done-state is server-authoritative.** Only the assignee can change it; other members see read-only status via `/history`.
9. **`effort` in `simulation/personas.py` is not the same as `burden_scores.score`** — the simulation's `effort` is a physical-effort chore attribute (1–5), a *generator input*. The app-level `burden` is the post-normalisation disutility produced by that generator (or by the UI).

---

## 13. Key References

- Aziz, Rauchecker, Schryen, Walsh — *Algorithms for Max-Min Share Fair Allocation of Indivisible Chores* — AAAI 2017
- Hosseini, Searns, Segal-Halevi — *Ordinal Maximin Share Approximation for Chores* — AAMAS 2022
- Bhaskar, Sricharan, Vaish — *On Approximate Envy-Freeness for Indivisible Chores and Mixed Resources* — APPROX/RANDOM 2021
- Lipton, Markakis, Mossel, Saberi — *On Approximately Fair Allocations of Indivisible Goods* — EC 2004 (goods baseline; fails for chores)
- Aziz, Caragiannis, Igarashi, Walsh — *Fair Allocation of Combinations of Indivisible Goods and Chores* — AAMAS 2022
- Aziz, Li, Moulin, Wu — *Algorithmic Fair Allocation of Indivisible Items: A Survey* — SIGecom Exchanges 2022
- Ebadian, Peters, Shah — *How to Fairly Allocate Easy and Difficult Chores* — 2022
