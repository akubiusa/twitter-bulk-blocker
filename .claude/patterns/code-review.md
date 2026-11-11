# Code Review Checklist

Review points specific to this repository. Each item points to the guide or pattern that explains it.

## Performance

- [ ] No per-user API or DB call inside a loop where a batch method exists (`get_users_info_batch`, `get_permanent_failures_batch`, `get_blocked_users_set`). See `anti-patterns.md`.
- [ ] Batch size stays at 50 for `UsersByRestIds`; delays go through `--delay` rather than new `time.sleep()` calls.
- [ ] User data is read through the `TwitterAPI` lookup methods so the three caches are used. See `guides/caching-strategy.md`.
- [ ] New SQL uses parameter placeholders, and any new filter column is justified against the table size. See `guides/performance-optimization.md`.

## Error handling

- [ ] Retry decisions go through `RetryManager.should_retry()` and the result tuple is unpacked (never used as a boolean).
- [ ] Permanent user states (`not_found`, `deactivated`, `suspended`) are recorded, not retried.
- [ ] Every retry loop has a bound; 429, 401 and account-lock handling reuses the existing `TwitterAPI` recovery methods. See `guides/error-handling.md`.
- [ ] Failures are recorded with status code, message and `user_status` via `record_block_result()` so `--retry` can classify them.
- [ ] No bare `except:` that hides a failure the caller needs to see.

## Security

- [ ] No cookie values, `ct0`, `auth_token` or full headers in logs, output or tests.
- [ ] No credentials or `cookies.json` committed.
- [ ] Input from the users file is validated (`ConfigManager._validate_schema`) before use; file names derived from user input are sanitized like the cache file names.

## Code quality

- [ ] Names say what the function does; magic numbers that already exist as constants (`MAX_RETRIES`, `cache_ttl`) are reused rather than repeated.
- [ ] Docstrings and comments follow the repository language convention in `AGENTS.md`.
- [ ] Orchestration stays in `BulkBlockManager`, HTTP in `TwitterAPI`, SQL in `DatabaseManager`. See `recommended.md`.
- [ ] New CLI options and environment variables are documented in `README.md`.

## Feedback format

State the problem, its impact, the proposed change, and a pointer to the relevant file in `.claude/guides/` or `.claude/patterns/`.

```markdown
**Problem**: `get_user_info_by_id()` is called once per user inside the loop.
**Impact**: One request per user; hits the rate limit and slows the run linearly.
**Suggestion**: Use `get_users_info_batch(ids, batch_size)`.
**Reference**: `.claude/patterns/anti-patterns.md`, "Per-item API or DB calls in a loop".
```
