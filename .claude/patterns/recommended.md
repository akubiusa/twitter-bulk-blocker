# Recommended Patterns

Patterns that match how the code is already structured. Follow them when adding features.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `api.py` (`TwitterAPI`, `HeaderEnhancer`) | HTTP requests to X, request headers, three-layer file cache, 401/403/429 recovery |
| `retry.py` (`ErrorClassifier`, `AdaptiveBackoffStrategy`, `RetryManager`) | Retry decisions and delays; no I/O |
| `database.py` (`DatabaseManager`) | SQLite access: block history, sessions, retry candidates, permanent-failure lookups |
| `config.py` (`ConfigManager`, `CookieManager`) | Users-file validation, cookie file loading |
| `manager.py` (`BulkBlockManager`) | Orchestration: batching, skip checks, block execution, statistics |
| `error_analytics.py`, `performance_monitor.py`, `user_status_monitor.py` | Optional monitoring tables and reports |
| `stats.py` | `--stats` output |

Keep orchestration in `BulkBlockManager`, keep HTTP details in `TwitterAPI`, and keep SQL in `DatabaseManager`.
New monitoring components are optional: construct them in a `try`/`except` in `BulkBlockManager.__init__` and set the attribute to `None` on failure, as the existing three are.

## Batch processing

Per batch of user IDs: one `get_permanent_failures_batch()` query, skip known failures and already-blocked users, one `get_users_info_batch()` call for the rest, then block each remaining user.
Record every outcome with `DatabaseManager.record_block_result()`, passing the status code, message and `user_status` so retries can be classified later.

## Error handling

- Decide retries with `RetryManager.should_retry()` and take the delay from `get_retry_delay()`; do not hard-code backoff.
- Unpack the result tuple: `should_retry, classification = retry_manager.should_retry(...)`.
- Call `record_retry_result()` after each retry so the adaptive backoff sees recent success rates (nothing in the current code calls it yet, so the success-rate multiplier always uses its neutral default).
- Treat `not_found`, `deactivated` and `suspended` as permanent and record them instead of retrying.

## Caching

Read and write user data only through the `TwitterAPI` lookup methods; they handle the lookup, profile and relationship layers and the 30-day expiry.
Cached relationship flags can be up to 30 days old; use `DatabaseManager.is_already_blocked()` (the block history) to decide whether a user was already blocked by this tool.

## Database access

- Use parameterized queries; build `IN (?, ?, ...)` placeholder lists for batch reads.
- Close connections explicitly.
  `with sqlite3.connect(...)` alone does not close them.

## Header enhancement

Defaults are enhancement on and forwarded-for off.
Use `--disable-header-enhancement` to turn the extra headers off if X starts rejecting requests, and `--enable-forwarded-for` only for experiments.
Programmatic equivalents are the `enable_header_enhancement` and `enable_forwarded_for` arguments of `BulkBlockManager` and `TwitterAPI`.

## Configuration

Paths come from CLI flags with env-var defaults (`TWITTER_COOKIES_PATH`, `TWITTER_USERS_FILE`, `TWITTER_BLOCK_DB`, `CACHE_DIR`); see `README.md` for the full list.
Add new options as `argparse` flags in `__main__.py` and pass them down through `BulkBlockManager`.
