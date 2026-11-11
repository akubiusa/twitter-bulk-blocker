Check the Twitter/X API state and local data health (read-only; changes nothing).

Scope: $ARGUMENTS (auth, cache, database, rate_limit, all; default all)

## auth

- Cookie file exists at `TWITTER_COOKIES_PATH` (default `cookies.json`; `/data/cookies.json` in Docker) and contains the Twitter-domain cookies (`CookieManager` in `twitter_blocker/config.py`).
- Look for 401/403 and authentication errors in the logs.
  For production, `.claude/commands/check-cinnamon-errors` and `.claude/cinnamon-logs.sh` do this.
- Header enhancement is on by default; `--disable-header-enhancement` turns it off and `--enable-forwarded-for` adds `x-xp-forwarded-for`.
  `get_effectiveness_report()` in `api.py` compares success rates with and without enhanced headers.

## cache

- Three file caches under `CACHE_DIR` (default `/data/cache`): `lookups/`, `profiles/`, `relationships/`; TTL 30 days.
- `TwitterAPI.get_cache_stats()` returns total/valid/expired counts per cache.
  The CLI does not expose it, so call it from a Python shell or count files with `find <dir> -name '*.json'`.

## database

- SQLite file at `TWITTER_BLOCK_DB` (`/data/block_history.db` in Docker).
- `python3 -m twitter_blocker --stats` prints totals, blocked, permanent failures (suspended/not_found/deactivated), failed and retry candidates.
- `sqlite3 <db> 'PRAGMA integrity_check;'` for file integrity.

## rate_limit

- Rate-limit information comes from response headers (`x-rate-limit-remaining`, `x-rate-limit-reset`) and is printed as `Rate Limit: remaining/limit` in `--debug` output.
- On a 429 the client waits until the reset time plus 10 s, clamped to 60-900 s (300 s when the header is missing).
- Do not assume fixed limits; read them from the headers.

## Report

- Overall status, per-area findings, detected problems, recommended actions.
