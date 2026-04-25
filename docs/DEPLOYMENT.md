# FairChore — Deployment

What you need to take FairChore from a local dev box to a public URL anyone
can open on their phone.

## Architecture

Single-process Flask app. The same Python process:
- Serves the JSON API under `/api/*`.
- Serves the React production build (everything else) from `frontend/build/`.

So one container, one port — no separate web/api split.

```
   browser  ──HTTPS──▶  reverse proxy  ──:5000──▶  waitress  ──▶  Flask app  ──▶  PostgreSQL
                       (Caddy / nginx /                                 │
                        Render / Railway)                               └── serves /api/* and the SPA
```

## Required environment variables

Set these before starting the app. Do **not** commit them to git.

| Name | Purpose | Example |
|---|---|---|
| `DATABASE_URL` | psycopg2-style PostgreSQL URI | `postgresql://user:pass@host:5432/fairchore` |
| `SECRET_KEY` | HMAC secret for JWT signing — **must be ≥32 random bytes**. Rotating it logs everyone out. | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ALLOWED_ORIGINS` | Comma-separated allowlist of front-end origins (no trailing slash) for CORS. | `https://fairchore.example.com` |
| `FLASK_DEBUG` | `false` in production. `true` shows tracebacks and disables caching. | `false` |

The app exits at start if `DATABASE_URL` or `SECRET_KEY` is missing — fail fast, no half-broken state.

## Steps

### 1. Provision PostgreSQL 14+

Point `DATABASE_URL` at it. Apply the schema once:

```bash
psql "$DATABASE_URL" < schema.sql
```

That creates the tables **and** seeds three demo households (Flat 42, The Smiths, Family Home) with the chore library and pre-rated members. To skip the demo seed in real production, manually apply only the `CREATE TABLE` statements at the top of [schema.sql](../schema.sql).

### 2. Build the React frontend

```bash
cd frontend
npm ci          # uses package-lock.json — reproducible install
npm run build   # produces frontend/build/ — Flask serves this directly
```

The `homepage` field in [frontend/package.json](../frontend/package.json) is unset, so the build assumes it is hosted at `/`. If you serve from a sub-path, set `"homepage": "/your-path"` and rebuild.

### 3. Start the API + static server

**Local / Windows / single-server:**
```bash
waitress-serve --listen=0.0.0.0:5000 backend.app:app
```

**Linux / cloud (uses gunicorn):**
```bash
pip install gunicorn==23.0.0
gunicorn -w 4 -b 0.0.0.0:5000 backend.app:app
```

Worker count: `2 × CPU + 1` is the gunicorn rule of thumb. For waitress the default thread count is usually fine.

**DO NOT** ship `python -m backend.app`. That uses Flask's dev server — single-threaded, no graceful shutdown, prints scary warnings.

### 4. Front the app with HTTPS

Flask is HTTP-only. Put a TLS-terminating reverse proxy in front:

- **Render / Railway / Fly / Heroku-style PaaS** — they handle HTTPS for you. Just expose the container on `$PORT`.
- **Self-host** — Caddy is the lowest-friction option (auto-renewing Let's Encrypt):

  ```
  fairchore.example.com {
      reverse_proxy localhost:5000
  }
  ```

- **nginx**: standard `proxy_pass http://127.0.0.1:5000;` block, plus a `try_files` rule for the SPA fallback if you want the proxy to serve static assets directly.

Once HTTPS is in place, set `ALLOWED_ORIGINS=https://fairchore.example.com` so CORS only accepts requests from that origin.

## Mobile

The PWA tags are already set in [frontend/public/index.html](../frontend/public/index.html):

- `viewport` with `width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no` — tap targets stay where they're meant to.
- `mobile-web-app-capable` + `apple-mobile-web-app-capable` — adds "Add to Home Screen" support on Android and iOS.
- `apple-mobile-web-app-status-bar-style` for the iOS status bar.

The CSS is responsive (mobile-first, no media-query breakpoints needed for the core flows). Test on a real phone after deploy — devtools mobile mode misses some quirks (notch handling, address-bar collapse).

## Verifying the deploy

After starting the production server, in order:

```bash
# 1. Backend is up
curl -fsSL https://fairchore.example.com/api/me -H "Authorization: Bearer junk"
# → 401 Unauthorized (correct — endpoint reachable, JWT verification ran)

# 2. Static assets served
curl -fsSL https://fairchore.example.com/ -o /dev/null
# → 200 OK, returns React's index.html

# 3. SPA fallback
curl -fsSL https://fairchore.example.com/some/random/route -o /dev/null
# → 200 OK (the catch-all in backend/app.py serves index.html so React-Router takes over)

# 4. CORS
curl -fsSL -X OPTIONS https://fairchore.example.com/api/login \
  -H "Origin: https://fairchore.example.com" \
  -H "Access-Control-Request-Method: POST" -i | grep -i access-control
# → headers should echo back the origin
```

## Known operational gotchas

- **Double-click on Confirm allocation** creates two allocation rounds. The UI disables the button while the request is in flight, but a network hiccup that delays the response can let a second click through. The DB UNIQUE constraint on `allocation_results.round_ts` only protects against exact-millisecond duplicates. Long-term fix: server returns a `confirm_token` from `/allocate` and `/confirm` only commits once per token.
- **`total_burden_accumulated` is per-user, not per-household.** A user in two households has one cumulative number. For the typical "members of one household" use case this is invisible; for power users it slightly cross-contaminates picking-order between their households.
- **No background job runner.** Everything is synchronous request/response. No scheduled cleanups, reminder notifications, or batch jobs — if you want them, add Celery + Redis or pick a serverless function provider for the cron pieces.
- **No rate limiting.** Flask sees a flood the same as one user. Put rate limits in the reverse proxy (nginx `limit_req_zone`, Caddy `rate_limit`, or your PaaS's built-in throttling).
- **`DATABASE_URL` shouldn't include `sslmode=disable` in production.** Most managed PostgreSQL providers require `sslmode=require` or stricter.

## What to monitor in production

- HTTP 5xx rate from `/api/*` (Flask traceback log will tell you which endpoint).
- DB connection pool — every endpoint opens a fresh `psycopg2.connect()` and closes it. Under load you may want `psycopg2.pool` or to switch to SQLAlchemy with a real pool.
- `assignment_history` row growth — unbounded, grows linearly with confirmed allocations × members. Plan for archival if a household sticks around for years.

## Database backups

Standard PostgreSQL `pg_dump`. Schedule daily, retain 7 days hot + monthly cold. The whole DB rarely exceeds a few MB unless an instance has tens of thousands of allocation rounds.

```bash
pg_dump "$DATABASE_URL" | gzip > fairchore-$(date +%F).sql.gz
```
