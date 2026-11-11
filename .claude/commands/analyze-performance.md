Analyze processing performance and identify bottlenecks.

Target: $ARGUMENTS (database, api, cache, all)

There is no built-in benchmark or metrics endpoint wired into the CLI.
Measure from the real run output (`--stats`, `--debug`, container logs) and from the cache and database files.

## Database (database/all)

- SQLite file: `TWITTER_BLOCK_DB` (`/data/block_history.db` in Docker), tables `block_history` and `process_log`.
- Time the queries behind `--stats` (`DatabaseManager.get_detailed_stats`) and the batch permanent-failure lookup (`get_permanent_failures_batch`) on the real file.
- Check for per-user queries inside loops (N+1).
  Batch loops in `twitter_blocker/manager.py` already fetch permanent failures once per batch.
- Check query plans with `EXPLAIN QUERY PLAN` before suggesting indexes; the code creates no explicit indexes.

## API (api/all)

- User lookup uses GraphQL `UsersByRestIds` (batched, default `batch_size=50`) and `UserByScreenName`; blocking uses `1.1/blocks/create.json`.
- Compare request rate with rate-limit waits (the wait is derived from `x-rate-limit-reset`, clamped to 60-900 s, 300 s fallback).
- `--delay` (default 1.0 s) is the pause between requests.
- Header enhancement (`--disable-header-enhancement`, `--enable-forwarded-for`): `get_effectiveness_report()` in `api.py` compares enhanced vs basic header success rates.

## Cache (cache/all)

- Three file caches under `CACHE_DIR` (default `/data/cache`): `lookups/` (screen name to user ID), `profiles/`, `relationships/<login user>/`.
- TTL is 30 days (`cache_ttl` in `api.py`).
- `TwitterAPI.get_cache_stats()` counts total/valid/expired entries per cache, but nothing in the CLI calls it.
  Hit rate is not recorded; count `CACHE HIT` lines in the logs to estimate it.

## Procedure

1. Collect throughput (blocks per minute) and error counts from the logs for the period in question.
2. Find where time goes: rate-limit waits, `--delay`, API latency, or database access.
3. Propose changes at the code level, ordered by effort (config change, code change, design change).
4. Report numbers with the measurement method; do not compare against targets that are not defined in the repository.
