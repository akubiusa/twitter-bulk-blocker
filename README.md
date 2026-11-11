# twitter-bulk-blocker

A Python CLI that blocks a large list of Twitter/X users. It authenticates with your browser cookies, looks users up through the GraphQL API, blocks them through the REST API, and records every result in SQLite so a run can be stopped and resumed.

## Features

- Skips users you follow or who follow you, and does not block a user already recorded as blocked in the SQLite history.
- Resumes where it left off: users already blocked are not processed again.
- Re-checks failed users (`--retry`, `--auto-retry`) by repeating the user lookup; the block request is not re-sent (see [Known limitations](#known-limitations)). Permanently failed accounts (`suspended`, `not_found`, `deactivated`) are classified as such.
- Batched lookups and a three-layer file cache (lookup, profile, relationship) with a 30-day TTL to reduce API calls.
- Waits and retries on rate limits (429) and reloads the cookie file when authentication fails.
- Debug tooling: `--debug`, `--test-user`, `--debug-errors`.
- Runs standalone or in Docker.

## Requirements

- Python 3 (the Docker image uses 3.15) with the packages in `requirements.txt` (`requests`, `pytz`).
- A **cookie file**: a JSON array exported from a logged-in x.com browser session. Each entry needs `name`, `value` and `domain`; only cookies for `.x.com`, `.twitter.com`, `x.com` and `twitter.com` are used (`ct0` is used as the CSRF token and `auth_token` is sent when present).
- A **users file**: the list of accounts to block (see below).

```bash
pip install -r requirements.txt
```

## Quick start

Outside Docker, first point the cache at a writable directory (every run that gets past argument parsing and the file checks, so not `--help` or `--version`, creates it on start; the default is `/data/cache`): `export CACHE_DIR=./cache`.

> **Warning:** running without `--all` is not a dry run. It really blocks the first 5 remaining users.

```bash
# Process the first 5 remaining users (test mode)
python3 -m twitter_blocker

# Show progress statistics
python3 -m twitter_blocker --stats

# Process every remaining user
python3 -m twitter_blocker --all

# Process every remaining user, then retry the failures
python3 -m twitter_blocker --all --auto-retry

# Look up one user without blocking (prints ID, name and follow relationship)
python3 -m twitter_blocker --test-user example_user

# Same lookup, with the raw API responses
python3 -m twitter_blocker --debug --test-user example_user

# Print the version
python3 -m twitter_blocker --version
```

More command lines are in [examples.md](examples.md).

## Users file

JSON with a `format` (`screen_name` or `user_id`) and a non-empty `users` list of strings.

```json
{
  "format": "screen_name",
  "users": ["example_user", "another_user"]
}
```

```json
{
  "format": "user_id",
  "users": ["1316469127914029057", "1234567890123456789"]
}
```

The default path is `video_misuse_detecteds.json` in the current directory.

## Command-line options

### Execution

| Option | Description |
|---|---|
| `--all` | Process all remaining users. Without it, only the first 5 remaining users are processed. |
| `--retry` | Re-check users whose block failed with a retryable error (see [Known limitations](#known-limitations)). |
| `--auto-retry` | With `--all`: run the retry pass after the main run. |
| `--reset-retry` | Reset the retry counter of failed users. |
| `--clear-errors` | Clear the stored error messages of failed users. |
| `--reset-failed` | Fully reset failed users (error message, retry count, response code, user status). |
| `--stats` | Print processing statistics and exit. |

### Limits

| Option | Description |
|---|---|
| `--max-users N` | Process at most N users (also limits `--retry`). Ignored in test mode, which always uses 5. |
| `--delay SECONDS` | Delay between requests (default `1.0`). For `user_id` files it is applied between batches of 50, for `screen_name` files after each block. |

### Debugging

| Option | Description |
|---|---|
| `--debug` | Print detailed API responses. |
| `--test-user SCREEN_NAME` | Look up a single user and exit. Nothing is blocked. |
| `--debug-errors` | Print up to 20 stored error-message samples. |
| `--version` | Print the version. |

### Request headers

| Option | Description |
|---|---|
| `--disable-header-enhancement` | Do not add the generated headers (`x-client-transaction-id`, `x-client-uuid`, `x-request-id`). |
| `--enable-forwarded-for` | Also send a generated `x-xp-forwarded-for` header (experimental). |

### Paths

| Option | Environment variable | Default |
|---|---|---|
| `--cookies PATH` | `TWITTER_COOKIES_PATH` | `cookies.json` |
| `--users-file PATH` | `TWITTER_USERS_FILE` | `video_misuse_detecteds.json` |
| `--db PATH` | `TWITTER_BLOCK_DB` | `block_history.db` |
| `--cache-dir PATH` | `CACHE_DIR` | `/data/cache` |

A command-line option overrides the environment variable, which overrides the default. The default cache directory `/data/cache` is created on start, so outside Docker point `CACHE_DIR` at a writable directory (for example `./cache`). `.env.example` lists the variables; the tool does not read `.env` itself, so load it into the environment first (`set -a; source .env; set +a`).

The cookie and users files are only checked up front for runs that block (`--all`, test mode); `--stats`, `--retry`, `--test-user`, `--debug-errors` and the reset commands start without that check.

## Docker

The image runs `python3 -m twitter_blocker` as user `appuser` (UID 1000) and defaults to `--help`. It presets:

```
TWITTER_COOKIES_PATH=/data/cookies.json
TWITTER_USERS_FILE=/data/users.json
TWITTER_BLOCK_DB=/data/block_history.db
CACHE_DIR=/data/cache
```

Mount a host directory at `/data` that is writable by UID 1000 and contains `cookies.json` and `users.json`:

```bash
docker build -t twitter-blocker .

docker run --rm -v "$(pwd)/data:/data" twitter-blocker --stats
docker run --rm -v "$(pwd)/data:/data" twitter-blocker --all --auto-retry
docker run --rm -v "$(pwd)/data:/data" twitter-blocker --debug --test-user example_user
```

Override a path by setting the variable and mounting accordingly:

```bash
docker run --rm \
  -v "$(pwd)/data:/data" \
  -v "$(pwd)/cookies:/cookies:ro" \
  -e TWITTER_COOKIES_PATH=/cookies/cookies.json \
  twitter-blocker --stats
```

Docker Compose:

```yaml
services:
  twitter-blocker:
    build: .
    volumes:
      - ./data:/data
    command: ["--stats"]
```

```bash
docker compose run --rm twitter-blocker
```

On SELinux hosts add `:Z` to the volume. The `APPLICATION_VERSION` build argument embeds a version string (CI sets it); without it the version is resolved at runtime (see `twitter_blocker/version.py`).

## How it works

1. Load the users file and validate its schema.
2. Skip users already blocked according to the block history.
3. Look users up in batches of 50 through GraphQL (`UsersByRestIds` for IDs, `UserByScreenName` for screen names), using the file cache first.
4. Skip users that are unavailable (`suspended`, `not_found`, `deactivated`), that you follow or who follow you, or that you already block.
5. Block the rest through the REST API and record the result (status, HTTP code, error message, retry count) in the `block_history` table.
6. Failed users with a retryable error become retry candidates.

Cache layout under `CACHE_DIR`: `lookups/` (screen name to user ID), `profiles/` (basic profile fields) and `relationships/<login user ID>/` (follow and block state, per logged-in account). Entries expire after 30 days.

### Error handling

- Permanent user states (`suspended`, `not_found`, `deactivated`) are not retried.
- The temporary state `unavailable` and HTTP 429, 500, 502, 503 and 504 failures become `--retry` candidates, up to 10 attempts, each waiting at least 30 seconds × 2^(previous attempts) since the last attempt. A failure is also a candidate when its HTTP code is empty or its stored message contains `temporarily`, `rate limit`, `timeout`, `server error` or `ユーザー情報取得失敗` (user lookup failed).
- HTTP 403 responses are classified (rate limit, account lock, "Unknown error", ...) in the log output only; the class is not stored. A failed block is recorded with its HTTP code and the message `Unknown error`, so a 403 failure is not a `--retry` candidate (403 is not in the code list and that message matches none of the patterns above). The `(permanent)` message suffix is only written for `suspended`, `not_found` and `deactivated` accounts.
- On authentication errors (401) the tool waits for the cookie file to change (up to 1 hour on the first attempt, 30 seconds on later ones), reloads it and retries; if the file did not change, it retries with the existing cookies. It exits after 10 failed attempts.

## Statistics output

`--stats` prints Japanese labels. An abridged example with translations in the comments:

```
=== 処理統計 ===                  # Processing statistics
全対象ユーザー: 2,308人            # Total target users
ブロック済み: 1,245人              # Blocked
...
失敗: 12人                         # Failed
  - リトライ上限到達: 2人          # Reached the retry limit
  - リトライ可能: 3人              # Retryable
リトライ候補: 3人                  # Retry candidates
```

All runtime output (progress, errors) is Japanese. Operations scripts under `.claude/` parse some of these lines, so the strings are kept as they are.

## Troubleshooting

| Symptom | What to do |
|---|---|
| Account locked (error 326) | Unlock the account at <https://twitter.com/account/access>, then run again. |
| HTTP 401 / authentication errors (log line `認証エラー検出`) | The cookies expired. Log in again, export a new cookie file and replace it; a running process picks up the change. |
| Rate limited (429) | The tool waits automatically. Use `--delay 2.0` or process in smaller chunks with `--max-users 50`. |
| Users file rejected | Check the [schema](#users-file): `format` is `screen_name` or `user_id`, `users` is a non-empty list. |
| Cache directory permission error | Create a writable directory and set `CACHE_DIR` to it. |
| Docker cannot write `/data` | The container user is UID 1000: make the host directory writable by it. |

To investigate failures: `python3 -m twitter_blocker --debug-errors`, then `python3 -m twitter_blocker --debug --test-user <name>`, then a small run such as `python3 -m twitter_blocker --debug --max-users 5` (which, like any run without `--all`, really blocks users).

## Project layout

```text
twitter_blocker/
├── __main__.py            # CLI entry point (argparse)
├── api.py                 # GraphQL/REST client, file cache, request headers, error recovery
├── config.py              # Users-file schema and cookie loading
├── database.py            # SQLite block history, failure queries
├── manager.py             # BulkBlockManager: batching, safety checks, retries
├── retry.py               # Failure classification and backoff
├── stats.py               # --stats output
├── error_analytics.py     # Error analytics tables and reports
├── performance_monitor.py # Performance metrics tables
├── user_status_monitor.py # Account-status tracking tables
└── version.py             # Version resolution
.claude/                   # Claude Code commands and docs for operating the production deployment
Dockerfile
examples.md
requirements.txt
```

## Known limitations

- `--retry` and the retry pass of `--auto-retry` only repeat the user lookup for failed users; they do not send the block request again (see `_process_retry_user` in `manager.py`).

## Notes

- Follow the Twitter/X terms of service and keep the request rate moderate. Use at your own risk.
- Never commit `cookies.json`, user lists or database files; they are git-ignored.
- Bug reports and pull requests are welcome. The repository has no `LICENSE` file.
