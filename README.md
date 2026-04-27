# FairChore

A web app that splits household chores fairly using fair-division algorithms designed for **chores** (negative-utility items), not goods.

> **COMP3200 Part III Individual Project**
> Author: Abdulmalik Alqahtani
> Supervisor: Dr. Bahar Rastegari
> University of Southampton

## Try it live

**https://fairchore.onrender.com**

Works on any modern browser, desktop or phone (it's a PWA — Add to Home Screen for an app-like icon). Demo accounts (password `test123` for all):

- `admin@flat42.com` — Flat 42 (4 students)
- `admin@smiths.com` — The Smiths (couple)
- `admin@family.com` — Family Home (2 parents + 2 teens)

Or register your own account and create a household from scratch.

> The app sleeps after 15 minutes of inactivity (free hosting tier). The first request after a quiet period takes 30–50 seconds to wake up — after that it's instant.

The full theoretical and design background lives in [docs/TECHNICAL_REFERENCE.md](docs/TECHNICAL_REFERENCE.md). This README is the practical "get it running" guide if you want to run it locally.

---

## What it does

A household admin adds chores. Each member rates how much they dislike each chore (1–4 emoji scale, normalised to a 100-point budget). The admin runs an **allocation** picking one of three fair-division algorithms; the system shows a preview, the admin confirms, and the chores are assigned. As members tick chores off, the system tracks cumulative load and biases future allocations toward whoever has done less recently.

Each chore is a **one-shot** instance — once allocated, it stays with its owner until completed and never re-enters the pool. To "redo" a chore, the admin adds a new one with the same name; the system auto-inherits the existing preferences so it can allocate immediately.

## Algorithms

| Algorithm | Fairness guarantee | Reference |
|---|---|---|
| Greedy Round-Robin | EF1 + (2 − 1/n) MMS approximation | Aziz et al., AAAI 2017 |
| Bag-Filling (paper) | 1-out-of-⌊2n/3⌋ ordinal MMS | Hosseini et al., AAMAS 2022 |
| Bag-Filling (practical) | Tighter threshold for small households | This project |
| Top-Trading Envy-Cycle Elimination | EF1 for chores | Bhaskar et al., APPROX 2021 |
| Random / Rotation | None (baselines) | — |

EF1 = "Envy-Free up to one item" — no member envies another's bundle by more than a single chore. Holds for unconstrained preferences; capability flags (`is_capable=false`) can introduce unavoidable envy when a member is locked out of part of the pool.

---

## Setup (local)

**Prerequisites**: Python 3.11+, Node 18+, PostgreSQL 14+ running on `localhost:5432`.

```bash
# 1. Python environment + deps
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux
pip install -r requirements.txt

# 2. Frontend deps
cd frontend && npm ci && cd ..

# 3. Configure the database
cp .env.example .env
#  → edit .env: set DATABASE_URL to point at your PostgreSQL,
#    and SECRET_KEY to any long random string.

# 4. Create + seed the database
python scripts/reset_db.py --yes
```

The reset script auto-creates the `fairchore` database if it doesn't exist, applies [schema.sql](schema.sql), and seeds 3 demo households (Flat 42, The Smiths, Family Home) with 10 users, 28 active chores, 44 inactive demo-library chores, and rated preferences for every non-admin member.

**Demo accounts** (password `test123` for all):
- `admin@flat42.com` — Flat 42 (4 students)
- `admin@smiths.com` — The Smiths (couple)
- `admin@family.com` — Family Home (2 parents + 2 teens)

Admin accounts intentionally start unrated so the demo can showcase the rating workflow.

## Running

Two terminals — backend and frontend, in dev mode:

```bash
# Terminal 1 — Flask API on :5000
python -m backend.app

# Terminal 2 — React dev server on :3000 (proxies /api/* to :5000)
cd frontend && npm start
```

Open [http://localhost:3000](http://localhost:3000) and log in.

### Production-mode (single port, served by Flask)

```bash
cd frontend && npm run build && cd ..
waitress-serve --listen=0.0.0.0:5000 backend.app:app
# now visit http://localhost:5000
```

## Tests

Four suites, ~370 tests total:

```bash
python scripts/run_tests.py
```

| Suite | What it covers | Runtime |
|---|---|---|
| `tests/unit/`        | Algorithm correctness, fairness metrics, persona generation | ~2 s |
| `tests/integration/` | Multi-round fairness across 17 scenarios × 3 algorithms     | <1 s |
| `tests/api/`         | All Flask endpoints, auth, two-phase flow, security, edge cases | ~70 s |
| `tests/db/`          | Schema constraints, seed data integrity, cascade behaviour     | ~8 s |

Or run any suite directly:

```bash
python -m pytest tests/api/                    # API only
python -m pytest tests/unit/test_algorithms.py # unit only
```

## Evaluation (for the report)

```bash
python -m evaluation.run_simulation     # 17 scenarios × 6 algos × 100 runs → results/
python -m evaluation.run_longitudinal   # 26-week repeated allocation study  → results/
```

Outputs to [results/](results/):
- `summary.csv` — raw 20,400 allocation results
- `summary_table.tex` — LaTeX-ready ranking table
- `key_findings.md` — markdown summary
- 13 PNG charts (EF1 by algorithm, MMS, workload balance, runtime, Pareto, longitudinal, etc.)

---

## Project structure

```
algorithms/         pure-Python algorithm library (no web/DB deps)
simulation/         synthetic household generator (17 scenarios × 12 personas)
evaluation/         batch simulation + longitudinal scripts → results/
backend/            Flask REST API, custom HS256 JWT, PostgreSQL
frontend/           React 18 single-page app
tests/              unit / integration / api / db
scripts/            reset_db, run_tests, run_eval
schema.sql          canonical PostgreSQL schema + demo seed
docs/               TECHNICAL_REFERENCE.md, ARCHITECTURE.md, DEPLOYMENT.md
```

Layering is strictly bottom-up:
`algorithms/` → `simulation/` → `evaluation/` (no web/DB) ⟂ `backend/` → `frontend/`. `tests/` import directly from any layer.

## Allocation lifecycle

```
POST /api/households/<id>/allocate          dry run — pick algo, get preview
   └─ pool = active chores with NO assignment_history row (one-shot)

POST /api/households/<id>/allocate/confirm  persist preview to assignment_history
   └─ shared confirmed_at timestamp identifies the round

POST /api/assignments/<id>/complete         assignee-only, stamps completed_at
DELETE same                                 toggles back to undone
```

A chore moves through `unallocated → assigned → completed` and never goes back. To do "Vacuuming" again, the admin adds a new chore titled `Vacuuming` — the backend auto-copies preferences and capability flags from the most recent matching chore so the new chore is immediately allocatable.

## Data model (condensed)

```
users(id, username, email, password_hash, total_burden_accumulated)
households(id, name, join_code, admin_id)
household_members(household_id, user_id)
chores(id, household_id, title, description, is_active)
burden_scores(user_id, chore_id, score INT, is_capable BOOL, UNIQUE(user, chore))
assignment_history(id, user_id, chore_id, burden_at_time, algorithm_used,
                   date_assigned, completed_at)
allocation_results(id, household_id, round_ts UNIQUE, algorithm,
                   scores_json JSONB, metrics_json JSONB)
```

## Storage and concurrency

- **Server-side**: PostgreSQL is the single source of truth. Every write goes there. The backend opens one psycopg2 connection per HTTP request and closes it in `finally`.
- **Browser**: `localStorage` holds only the JWT auth token + accessibility prefs (text size, high-contrast, reduced motion). `sessionStorage` holds the last-used algorithm so navigation doesn't reset the choice. **No chore data, no preferences, no allocation results live in browser storage.**
- **Multi-user**: each user has their own JWT. Multiple users in the same household can be logged in and acting concurrently. Allocations are admin-only; rating preferences and ticking off chores are per-user. The DB enforces ownership via `WHERE user_id = …` — there's no way for one user to mark another's chore complete (returns 403).

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full deployment walkthrough (env vars, schema apply, WSGI server, HTTPS proxy, mobile/PWA, operational gotchas).

Short version: any PaaS that runs Python 3.11+ and offers PostgreSQL works. Build command runs `pip install -r requirements.txt && cd frontend && npm ci && npm run build`. Start command is `waitress-serve --listen=0.0.0.0:$PORT backend.app:app`. Set `DATABASE_URL`, `SECRET_KEY`, `ALLOWED_ORIGINS`, `FLASK_DEBUG=false`.

## License

Academic project — not licensed for redistribution.
