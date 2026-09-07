# db_proxy — campus MySQL access for the Render deployment

## Why this exists
Render's backend can't reach campus MySQL directly (no inbound access to the
campus network). This is a thin HTTP relay that runs ON the campus machine,
next to MySQL, and gets exposed via a free Cloudflare Quick Tunnel (HTTP-only,
no domain needed). `database.py`'s `connect()` talks to it over HTTPS when
`DB_PROXY_URL` is set — every route file (`routes_*.py`) is unchanged.

## One-time setup (on the campus machine)

1. `cd db_proxy`
2. `pip install -r ../requirements.txt` (fastapi, uvicorn, pymysql/mysql-connector, requests, python-dotenv already in the main requirements.txt)
3. `cp .env.example .env`, fill in:
   - `MYSQL_*` — same campus MySQL credentials the main app already uses
   - `PROXY_SHARED_KEY` — generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
     Save this value — you'll need it on Render too.

## Every time you start working (two terminals, both on campus machine)

**Terminal 1 — start the proxy:**
```
cd db_proxy
uvicorn main:app --host 0.0.0.0 --port 8010
```

**Terminal 2 — tunnel it:**
```
python run_cloudflare.py --port 8010
```
Copy the printed `https://xxxxx.trycloudflare.com` URL.

## On Render (set these env vars on the backend service)
```
DB_PROXY_URL=https://xxxxx.trycloudflare.com     <- from Terminal 2 above
DB_PROXY_KEY=<the PROXY_SHARED_KEY you generated>
```
Leave `MYSQL_HOST` etc unset on Render — they're not used when `DB_PROXY_URL` is set.

## ⚠️ The URL changes every restart
Cloudflare Quick Tunnels are free and require no login, but the tradeoff is:
**the URL is different every time `cloudflared` restarts.** If the campus
machine reboots, sleeps, or you Ctrl+C the tunnel, you must:
1. Restart Terminal 2, get the new URL
2. Update `DB_PROXY_URL` on Render to the new URL
3. Render redeploys automatically on env var change

There is no way to avoid this on the free tier without a domain (see main
conversation history — Option A was the domain-based alternative, rejected).

## Operational reality
- Campus machine must stay on and both terminals must keep running for the
  deployed app's database to work at all. If either stops, Render's app will
  get `OperationalError: db_proxy unreachable` on every DB call — this is
  the expected, correctly-surfaced failure mode, not a bug.
- Sessions auto-expire after 30s idle (crash safety) — irrelevant in normal
  use since routes open/close a session within one request.
- Check `http://127.0.0.1:8010/v1/health` locally, or `<tunnel-url>/v1/health`
  remotely, to confirm the proxy + MySQL connection are both alive. No auth
  needed on this endpoint (it returns no secrets).

## What this does NOT do
- No business logic — it has zero knowledge of students/attendance/anything.
- No arbitrary database selection — always connects to its own `.env`'s
  `MYSQL_DATABASE`, ignores any db_name a caller might try to send.
- No auth bypass flag exists anywhere in `main.py` — don't add one, even
  temporarily. A public tunnel URL with no auth check is an open MySQL
  gateway into the campus network.

## Reversing this (going back to direct-connect, e.g. moving to hosted MySQL)
Unset `DB_PROXY_URL` on Render, point `MYSQL_HOST` at a real reachable
MySQL host instead. `database.py`'s direct-connect path was never removed —
this is a one-env-var change, not a code change.
