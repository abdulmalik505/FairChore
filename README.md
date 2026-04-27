# FairChore

A web app that splits household chores fairly using fair-division algorithms designed for **chores** (negative-utility items), not goods.

> **COMP3200 Part III Individual Project** · Abdulmalik Alqahtani · supervised by Dr Bahar Rastegari · University of Southampton

## Live

**[fairchore.onrender.com](https://fairchore.onrender.com)**

Demo accounts (password `test123`):

- `admin@flat42.com` — Flat 42 (4 students)
- `admin@smiths.com` — The Smiths (couple)
- `admin@family.com` — Family Home (2 parents + 2 teens)

> Free hosting tier, so the first request after 15 min idle takes ~30 s to wake up. Then it's instant.

## Algorithms

Implemented in `algorithms/`:

- **Round-Robin** (Aziz et al., 2017) — EF1 + (2 − 1/n) MMS approximation.
- **Bag-Filling** (Hosseini et al., 2022) — paper variant + a tighter practical variant.
- **Top-Trading Cycle Elimination** (Bhaskar et al., 2021) — EF1 for chores.
- Random and Rotation as baselines.

EF1 = "Envy-Free up to one item": no member envies another's bundle by more than a single chore.

## Run locally

Requirements: Python 3.11+, Node 18+, PostgreSQL 14+.

```bash
python -m venv venv && source venv/bin/activate    # macOS/Linux
python -m venv venv && venv\Scripts\activate       # Windows
pip install -r requirements.txt
cd frontend && npm ci && cd ..

cp .env.example .env                                # then edit DATABASE_URL + SECRET_KEY
python scripts/reset_db.py --yes                    # creates DB, applies schema, seeds demo

# dev mode (two terminals)
python -m backend.app                               # API on :5000
cd frontend && npm start                            # SPA on :3000

# or production-mode (single port)
cd frontend && npm run build && cd ..
waitress-serve --listen=0.0.0.0:5000 backend.app:app
```

## Tests

```bash
python scripts/run_tests.py
```

Four suites, ~370 tests covering algorithm correctness, multi-round fairness across 17 scenarios, every Flask endpoint with security and edge cases, and schema integrity.

## Evaluation

```bash
python -m evaluation.run_simulation       # 17 scenarios × 6 algos × 100 runs
python -m evaluation.run_longitudinal     # 26-week repeated-allocation study
```

Outputs to `results/`: `summary.csv` (20,400 rows of raw data), `summary_table.tex`, `key_findings.md`, and five charts:

- `ef1_by_algorithm.png` — EF1 satisfaction per algorithm with 95% CIs
- `mms_comparison.png` — MMS ratio per algorithm
- `constrained_vs_unconstrained.png` — effect of capability flags
- `pareto_workload_runtime.png` — fairness vs runtime trade-off
- `longitudinal_member_trajectory.png` — temporal-reciprocity convergence over 26 weeks

## Deployment

Any PaaS with Python 3.11+ and PostgreSQL. Current deploy is on Render.

- Build: `pip install -r requirements.txt && cd frontend && npm ci && npm run build`
- Start: `waitress-serve --listen=0.0.0.0:$PORT backend.app:app`
- Env vars: `DATABASE_URL`, `SECRET_KEY`, `ALLOWED_ORIGINS`, `FLASK_DEBUG=false`
- Apply schema once: `psql "$DATABASE_URL" < schema.sql`

## Project structure

```
algorithms/    pure-Python algorithm library (no web/DB deps)
simulation/    synthetic household generator (17 scenarios)
evaluation/    batch + longitudinal scripts → results/
backend/       Flask REST API, custom HS256 JWT, PostgreSQL
frontend/      React 18 single-page app, served by Flask in production
tests/         unit / integration / api / db
schema.sql     canonical PostgreSQL schema + demo seed
```

## License

Academic project — not licensed for redistribution.
