# Anti-Patterns

Things to avoid in this codebase, with the existing alternative to use instead.

## Per-item API or DB calls in a loop (N+1)

Looping over users and calling `is_permanent_failure()` and `get_user_info_by_id()` for each one costs one query and one request per user.
Use the batch methods instead:

```python
permanent_failures = self.database.get_permanent_failures_batch(batch_ids, user_format)
processable = [u for u in batch_ids if u not in permanent_failures]
users_info = self.api.get_users_info_batch(processable, batch_size)
```

This is the pattern `BulkBlockManager._process_users_batch()` follows.

## Ignoring the rate limit

Do not retry 429s in a tight loop or add your own request counters.
`TwitterAPI._calculate_wait_time()` already derives the wait from `x-rate-limit-reset` (60-900 s, 300 s fallback), and every request method sleeps and retries once.
Keep `--delay` at its default unless you have measured a reason to change it.

## Hiding errors or retrying without limit

- Do not swallow exceptions into a generic `{"success": False}`; return or record the status code and message so `RetryManager` and the `--retry` queries can classify them.
- Do not add `while True` retry loops.
  Retries are bounded by `RetryManager.MAX_RETRIES` (10) for queued failures and by `_max_auth_retries` (10) for 401/account-lock recovery.
- Do not retry permanent user states (`not_found`, `deactivated`, `suspended`).
- Do not compare the tuple returned by `RetryManager.should_retry()` to a boolean or negate it; use `should_retry(...)[0]`.

## Bypassing the caches

Calling the GraphQL endpoints directly for a user that may already be cached wastes rate-limit budget.
Go through `get_user_info()`, `get_user_info_by_id()`, `get_users_info_batch()` or `get_users_info_by_screen_names()`, which read and fill the lookup, profile and relationship caches.
Do not write cache files by hand; relationship entries live under a per-login-account directory.

## Leaking SQLite connections

`with sqlite3.connect(...)` commits or rolls back but does not close the connection.
Close connections explicitly (or use `contextlib.closing`) in new `DatabaseManager` code.

## Logging secrets

Never print or log cookie values, `ct0`, `auth_token` or full request headers.
`_log_enhanced_headers()` prints only the generated extra headers; do not extend it to the full header set.
Do not commit `cookies.json`; it belongs in the git-ignored data directory.

## Hard-coded configuration

File paths and the cache directory come from CLI flags with environment-variable defaults (`TWITTER_COOKIES_PATH`, `TWITTER_USERS_FILE`, `TWITTER_BLOCK_DB`, `CACHE_DIR`); behavior toggles come from CLI flags (`--delay`, `--disable-header-enhancement`, `--enable-forwarded-for`).
Add new settings the same way instead of embedding values in call sites.
