# Performance Optimization

What the tool does to keep API and database load low, and how to measure it. Verified against `manager.py`, `api.py`, `database.py` and `performance_monitor.py`.

## Batching

- `process_bulk_block(max_users, delay=1.0, batch_size=50)` processes user IDs in batches of 50.
  `delay` (CLI `--delay`, default 1.0 s) is the pause between batches for user-ID input and after each executed block for screen-name input.
- For user IDs, each batch first does one `get_permanent_failures_batch()` query, then `get_users_info_batch()` for the users not already blocked or skipped.
  `get_users_info_batch()` serves cached users locally and sends the rest to `UsersByRestIds` in chunks of `batch_size`.
- For screen names, `get_users_info_by_screen_names()` resolves names one by one (UserByScreenName returns relationship flags, so it fills all caches) and only batches the relationship fetch for users that were found in the lookup cache.
- Never add a per-user API or DB call inside a loop where a batch method exists (`get_users_info_batch`, `get_permanent_failures_batch`, `get_blocked_users_set`).

## Database

- `get_permanent_failures_batch()` uses a single `IN (?, ?, ...)` query.
  SQLite limits the number of bound parameters per statement (999 on older builds, 32766 on SQLite 3.32+), so keep the batch size at or below the existing 50.
- The schema (`block_history`, `process_log` in `database.py`) defines no indexes except the `UNIQUE(user_id)` constraint.
  Queries by `screen_name` or `status` scan the table; add an index only after measuring a slowdown on a large `block_history`.
- Most `DatabaseManager` methods open a connection with `sqlite3.connect()` and call `close()` explicitly; `is_permanent_failure`, `get_permanent_failure_info` and `get_permanent_failures_batch` use only `with sqlite3.connect(...)`.
  `with sqlite3.connect(...)` commits or rolls back but does not close the connection; call `close()` as well (or wrap it in `contextlib.closing`) when adding new queries.

## Caching

Lookup, profile and relationship results are cached for 30 days; see `caching-strategy.md`.
A fully cached run makes no lookup requests, so the cache hit rate is the main lever for run time after the first pass.

## Measuring

- `PerformanceMonitor` (created by `BulkBlockManager`, optional) records throughput into `performance_metrics`, `processing_speed_stats` and `performance_alerts` in the same SQLite file.
- Per-window bottleneck flags: fewer than 1 request/s, average processing time above 5 s, success rate below 80%, or error rate above 20%.
- Alerts from `check_degradation_thresholds()`: below 0.1 request/s (CRITICAL), success rate below 50% (HIGH), average processing time above 10 s (MEDIUM).
- `analyze_performance_degradation()` compares the last hour of a session with its first hour.
- `--stats` prints block statistics; `TwitterAPI.get_cache_stats()` returns cache entry counts.

Real throughput is bounded by `--delay` and the X rate limits (the 429 wait is 60-900 s), not by local processing.
Compare runs against your own baseline from the tables above rather than a fixed target.

## Checklist for a change

- [ ] Any new loop over users uses an existing batch method or adds one.
- [ ] New cache reads go through `_combine_profile_and_relationship()` or the existing cache helpers.
- [ ] New DB connections are closed.
- [ ] `--delay` and batch size are not lowered without considering the 429 behavior.
