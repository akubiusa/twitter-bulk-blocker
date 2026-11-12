# Common Issues and Troubleshooting

Console output of the tool is in Japanese; the Japanese strings quoted below are the literal messages to grep for.

## Authentication

### 401 Unauthorized

Symptom: `認証エラー検出 (...): Cookie再読み込み＋リトライ N/10`, ending in `SystemExit("Authentication failed - Cookie is invalid")` after 10 retries.

How the tool recovers (`TwitterAPI._handle_auth_error`):
- On the first retry it polls the cookies file's mtime for up to 1 hour; later retries wait up to 30 s.
- Whenever the file changed (or the wait expired) it clears the cookie cache and retries with exponential backoff (`2^(n-1)` s, capped at 60 s, with jitter).
- So refreshing the cookies file while the tool waits is enough; no restart is needed.

Checks:
1. `cookies.json` must contain `ct0` and `auth_token` for `.x.com` / `.twitter.com` (`CookieManager.TWITTER_DOMAINS`).
   `ct0` is sent as the CSRF token and `auth_token` as the auth token (`TwitterAPI._build_graphql_headers`).
2. Export fresh cookies from a logged-in browser session and overwrite the file at the path given by `--cookies` / `TWITTER_COOKIES_PATH` (default `cookies.json`, `/data/cookies.json` in the Docker image).
3. `CookieManager` caches cookies for at most 30 s and re-reads on mtime change, so a replaced file is picked up automatically.
4. If fresh cookies still fail, check the account in a browser (locked, suspended, verification required).

### 403 with account lock or anti-bot response

- A 403 whose error message contains `account is temporarily locked`, `account has been locked`, `suspicious activity` or `verify your account` goes through the same recovery flow as a 401 (`_handle_account_lock_error`).
- Other 403 bodies are classified by `ErrorClassifier.classify_403_error` (`rate_limit`, `auth_required`, `permission_denied`, `account_restricted`, `header_issue`, `anti_bot`, `ip_blocked`, `unknown_403`; first matching rule wins).
- Only `account_restricted` and `ip_blocked` are treated as non-retryable; every other 403 is retried.
- After 20 accumulated 403s, `CookieManager.force_refresh_on_error_threshold` clears the cookie cache, resets the counters and **blocks for 30 minutes** (log: `緊急クールダウン開始`).
  This is a blocking `time.sleep(1800)` with no signal handling around it, so it is expected behavior, not a hang.
  Stopping the container during it is safe for the data (SQLite rolls back an unfinished write on the next open); `docker stop` may take the full grace period before Docker kills the process (unverified).
- If 403s persist, try `--delay` above `1.0`, and check the header flags (`--disable-header-enhancement`, `--enable-forwarded-for`).

### GraphQL feature flags rejected

GraphQL requests send the flags returned by `TwitterAPI._get_graphql_features` in `api.py`.
When Twitter changes the expected flags, lookups start failing (typically 400 responses on the GraphQL endpoint; confirm in the `--debug` output).
To fix: copy the current `features` query parameter from a real `UserByScreenName` / `UserByRestId` request in the browser network tab and update that method.

## Rate limits

### 429

- Handling (`TwitterAPI._calculate_wait_time`): wait until `x-rate-limit-reset` plus 10 s, clamped to 60-900 s; 300 s when the header is missing or invalid.
  The request is then retried once.
  Log: `レートリミット検出 (...): N.N分間待機します`.
- The code does not hard-code any per-endpoint request quota; it only reacts to 429 responses and `x-rate-limit-reset`. Twitter's actual quotas are not documented in this repository (unverified).
- If 429s are frequent, raise `--delay` and re-run; already-processed users are skipped via the DB, and the lookup/profile caches avoid repeated GraphQL calls.

### Failed rows to retry later

- Rows with `status='failed'` are retried by `--retry` (or `--all --auto-retry`).
- Retry decisions come from `RetryManager.should_retry`: at most `MAX_RETRIES = 10` retries; `not_found`, `deactivated`, `suspended` are permanent; `unavailable` and status codes 403/429/500/502/503/504 are retried.
- `--reset-retry` zeroes retry counts, `--clear-errors` clears error messages, `--reset-failed` resets error message, retry count, response code and user status of all failed rows.
- `--clear-errors` (`clear_error_messages` in `database.py`) only sets `error_message = NULL` on failed rows and leaves `last_retry_at` untouched.
- `--debug-errors` prints sample stored error messages.

## "User not found" / suspended users

- A lookup that reports the user as missing, suspended or deactivated is recorded in `block_history` as `status='failed'` with `user_status` set (`not_found`, `suspended`, `deactivated`).
- `--stats` shows the counts (`suspended`, and `unavailable` which also covers `not_found` / `deactivated`).
- Intended behavior: `RetryManager.should_retry` treats these as permanent and the error message gets a `(permanent)` suffix.
  Actual behavior today: `_check_user_unavailable` / `_execute_block` in `manager.py` test the `should_retry` tuple as a boolean, so every such user is recorded as retryable, without the suffix (see the known-issue note in `guides/error-handling.md`).
  Expect them to show up again in `--retry` candidates until that is fixed.

## SQLite

### `database is locked`

- Every `DatabaseManager` method opens its own `sqlite3.connect(db_file)` with the default 5 s busy timeout; no `journal_mode` pragma is set anywhere in the code, so the DB uses SQLite's default rollback journal, not WAL.
- Usual cause: two processes using the same DB file (for example a long `--all` run plus a manual `--stats`/`--retry` on the same file, or two containers sharing one volume).
- Check for other processes with `fuser block_history.db` (or `lsof`), stop the extra one, and retry.
- `block_history.db-journal` next to the DB is a hot journal from an interrupted write; SQLite rolls it back automatically on the next open.
  Do not delete it by hand.

### Duplicate rows / `UNIQUE constraint failed`

`block_history` is `UNIQUE(user_id)` and `DatabaseManager.record_block_result` uses `INSERT OR REPLACE`, so the same user is overwritten, not duplicated.
A uniqueness error therefore indicates code that inserts into `block_history` directly; route writes through `record_block_result` instead.

## Network

- The tool calls `requests.get` / `requests.post` without a timeout; a stalled connection can hang until the OS gives up.
  If a run appears stuck without a rate-limit or cooldown message, check connectivity from the same host/container and restart the run (progress is stored in SQLite, so it resumes).
- Behind a proxy, `requests` honors `HTTP_PROXY` / `HTTPS_PROXY`; verify these are not set to a dead proxy.

## File and permission errors

- `PermissionError` on the DB, cache directory or cookies file: check ownership of the mounted data volume.
  The Docker image runs as `appuser` and declares `VOLUME /app/data`, while its default env vars point at `/data/...` (`TWITTER_COOKIES_PATH=/data/cookies.json`, `TWITTER_USERS_FILE=/data/users.json`, `TWITTER_BLOCK_DB=/data/block_history.db`, `CACHE_DIR=/data/cache`; see `Dockerfile`), so mount the volume at the path the env vars point to or override them.
- The cache directory is created on startup (`lookups/`, `profiles/`, `relationships/` under `--cache-dir`), so the parent must be writable.
- `ValueError` from the users file means the schema is wrong; the required shape is `{"format": "user_id" | "screen_name", "users": [non-empty list]}`.

## Quick diagnosis

```bash
python3 -m py_compile twitter_blocker/*.py            # syntax sanity
python3 -m twitter_blocker --stats                    # DB readable, counts plausible
python3 -m twitter_blocker --test-user <name> --debug # auth + GraphQL lookup, no block
sqlite3 block_history.db "PRAGMA integrity_check;"
```

For the production host, see `.claude/cinnamon-connection.md` and `.claude/operations/cinnamon-server.md`.
For disaster handling, see `workflows/emergency.md`.
