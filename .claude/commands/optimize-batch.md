Find and fix inefficient batch handling (N+1 queries, per-item API calls).

Target: $ARGUMENTS (user_lookup, database_query, api_calls, all)

## Current behavior to check first

- `BulkBlockManager.process_bulk_block(max_users, delay, batch_size=50)` in `twitter_blocker/manager.py` processes users in batches of `batch_size`.
- Per batch, permanent failures are loaded with one query (`DatabaseManager.get_permanent_failures_batch`); only unchecked IDs go to the API.
- `TwitterAPI.get_users_info_batch(user_ids, batch_size=50)` checks the caches, then sends batched GraphQL `UsersByRestIds` requests.
- Screen-name inputs are resolved through the lookup cache, then `UserByScreenName`.
- Blocking is one `blocks/create.json` request per user, followed by the `--delay` pause (default 1.0 s).
- Each `DatabaseManager` method opens its own SQLite connection (`sqlite3.connect`), and the code sets no PRAGMAs and creates no explicit indexes.

## user_lookup

- Is `batch_size` appropriate for `UsersByRestIds` given rate-limit waits?
- Are cache and permanent-failure checks done before the API call for every ID?

## database_query

- Look for per-user queries inside loops and for repeated connection opens in hot paths.
- Consider batching inserts into one transaction and measure with `EXPLAIN QUERY PLAN` before adding indexes.

## api_calls

- Look for requests that could be combined and for avoidable header-generation cost.

## Verification

1. Measure before and after on the same input: users per minute, API request count, cache hit lines, error count.
2. `python3 -m py_compile twitter_blocker/*.py`, then a debug run with `--max-users` on a small set.
3. Roll out gradually on production (one service first); see `.claude/operations/` for the host layout.
