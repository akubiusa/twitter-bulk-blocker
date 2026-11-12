# Error Handling

How the tool classifies and retries failures. Source of truth: `twitter_blocker/retry.py` (`ErrorClassifier`, `AdaptiveBackoffStrategy`, `RetryManager`), plus the recovery methods in `api.py` and the retry queries in `database.py`.

## Retry decision (`RetryManager.should_retry`)

Checked in this order, first match wins:

1. `retry_count >= MAX_RETRIES` (10): no retry (`max_retries_exceeded`).
2. `user_status` in `PERMANENT_FAILURES` (`not_found`, `deactivated`, `suspended`): no retry (`permanent_failure`).
3. `user_status` in `TEMPORARY_FAILURES` (`unavailable`): retry.
4. HTTP 403: classify with `ErrorClassifier`; retry unless the type is `account_restricted` or `ip_blocked` (priority 3).
5. Status code in `RETRYABLE_STATUS_CODES` (429, 500, 502, 503, 504): retry.
6. Error message contains one of `RETRYABLE_MESSAGES` (`temporarily unavailable`, `rate limit`, `timeout`, `server error`, `unknown error`) or the tool's own `ユーザー情報取得失敗`: retry.
7. No status code and a message that does not contain "permanent": retry as a presumed network failure.
8. Otherwise: no retry (`no_retry_condition_met`).

The function returns a tuple `(should_retry, classification)`.
Callers must unpack it or index `[0]`; `not retry_manager.should_retry(...)` is always `False` because a non-empty tuple is truthy.

## 403 classification (`ErrorClassifier.classify_403_error`)

Keyword rules on the lowercased response body, checked in this order:

| Type | Trigger (summary) | Priority |
|---|---|---|
| `rate_limit` | "rate limit", "too many requests", or `x-rate-limit-remaining: 0` | 1 |
| `auth_required` | authorization / authenticate / invalid token / credential | 2 |
| `permission_denied` | permission / access denied / not authorized / forbidden | 2 |
| `account_restricted` | "account" together with restricted / limited / suspended / locked | 3 |
| `header_issue` | header / user-agent / "missing" and "required" | 1 |
| `anti_bot` | bot / automated / suspicious / unusual activity / verification | 2 |
| `ip_blocked` | "ip" together with blocked / restricted | 3 |
| `unknown_403` | "unknown error" or anything else | 2 |

Priority: 1 = fixable immediately, 2 = needs adjustment, 3 = serious.
Matching is by substring, so the first matching rule wins even when a later rule would fit better.

## Retry delay (`RetryManager.get_retry_delay`)

- 403 with a classification: `AdaptiveBackoffStrategy.calculate_backoff_delay()`.
  `delay = base_delay * type_multiplier * min(2**retry_count, 8) * success_rate_multiplier`, clamped to 10-600 s (5 s minimum for `header_issue`; 1800 s maximum for `ip_blocked` and `account_restricted`).
  Type multipliers: `rate_limit` 2.0, `auth_required` 1.5, `permission_denied` 1.0, `account_restricted` 3.0, `header_issue` 0.5, `unknown_403` 2.5, `anti_bot` 3.0, `ip_blocked` 4.0.
  The success-rate multiplier uses the last 5 minutes of attempts for that type: 2.0 below 30%, 1.5 below 50%, 0.8 above 80%, otherwise 1.0 (0.5 success rate assumed with no data).
- 403 "unknown error" without a classification: `base_delay * 3 * 2**retry_count`.
- Everything else: `base_delay * 2**retry_count` (`base_delay` defaults to 30 s).

## Failed-user retries (`--retry`)

`DatabaseManager.get_retry_candidates()` returns `block_history` rows with `status = 'failed'`, `retry_count < 10`, a transient-looking failure (`user_status = 'unavailable'`, response code 429/5xx or NULL, or a retryable message), and either a NULL `last_retry_at` (set by `--reset-retry` / `--reset-failed`; no backoff pending) or a non-NULL `last_retry_at` that is at least `30 * 2**retry_count` seconds old.
`--reset-retry`, `--clear-errors` and `--reset-failed` reset the retry counters, error messages, or both plus the status of failed users.

`is_permanent_failure()` and `get_permanent_failures_batch()` apply `RetryManager.should_retry` to a user's failed row to decide whether to skip the user.
`BulkBlockManager` calls the batch version once per batch before any API lookup.

> Known issue: both functions negate the tuple returned by `should_retry` (see above), so they never report a permanent failure.
> The two `if self.retry_manager.should_retry(...)` checks in `manager.py` (`_check_user_unavailable`, `_execute_block`) have the opposite problem and are always true.
> Fix by indexing `should_retry(...)[0]`.

## HTTP-level recovery in `TwitterAPI`

| Condition | Behavior |
|---|---|
| 429 | Sleep per `_calculate_wait_time()` (see `api-patterns.md`) and retry once |
| 401 | `_handle_auth_error()`: wait for the cookie file to change (1 h on the first retry, 30 s later), clear the cookie cache, back off `min(2**(n-1), 60)` s with jitter, retry; up to 10 attempts, then `SystemExit` |
| 403 with a lock message | `_handle_account_lock_error()`: same retry budget as 401 |
| 10 consecutive errors, or 50 errors in a 30-minute window | Reload cookies and retry once (`_handle_frequent_errors`, waits up to 30 s for a cookie refresh) |
| 20 accumulated 403s | `CookieManager.force_refresh_on_error_threshold()` clears the cookie cache and pauses for 30 minutes |

Counters for consecutive errors and 403s reset on the next success; the 30-minute window keeps running.

## Early warnings

`_check_early_warning_conditions()` prints a warning (at most once per 10 minutes) when:

- 20 or more retry attempts were recorded in the last 5 minutes (`ERROR_SPIKE`),
- the recent retry success rate is below 30% (`HIGH_ERROR_RATE`), or
- a 403 is classified `anti_bot`, `ip_blocked` or `account_restricted` (`CRITICAL_ERROR_TYPE`).

`_check_long_term_403_patterns()` adds runtime-based warnings (2.0-3.5 h and beyond); these are heuristics, not tuned limits.

## Analytics

`HTTPErrorAnalytics`, `PerformanceMonitor` and `UserStatusMonitor` are optional: `BulkBlockManager` sets the attribute to `None` if one fails to import or initialize, and the tool continues without it.
`TwitterAPI.get_comprehensive_error_analysis()` combines the 403 stats, header effectiveness and analytics data into one report.
