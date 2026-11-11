# Testing and Verification Guide

The repository has no committed test suite and no `tests/` directory.
CI (`.github/workflows/docker.yml`) only builds the Docker image.
`pytest`, `flake8`, `mypy` and `black` are installed in the Copilot dev environment (`.github/workflows/copilot-setup-steps.yml`) but are not enforced anywhere.
Do not claim "tests pass" for this repo; report what you actually ran.

## Local quality gate

```bash
python3 -m py_compile twitter_blocker/*.py
```

## Verifying a change against real behavior

Run the CLI against a single user with debug output (requires a valid cookies file):

```bash
python3 -m twitter_blocker --test-user <screen_name> --debug   # user lookup only, does not block
python3 -m twitter_blocker --stats                              # read-only: DB statistics
python3 -m twitter_blocker --debug-errors                       # read-only: stored error samples
```

- `--test-user` performs a lookup (`get_user_info`) and prints the result; it never calls the block endpoint.
- Running with no flags is "test mode", not a dry run: it really blocks the first 5 remaining users of the users file.
  Use `--all` for a full run; `--max-users N` caps `--all` and `--retry` runs (test mode ignores it), and `--delay SECONDS` (default `1.0`) slows requests down.
- Point `--db` and `--cache-dir` at scratch paths to avoid touching production data.
- `--stats`, `--retry`, `--reset-retry`, `--clear-errors`, `--reset-failed`, `--debug-errors` and `--test-user` skip the startup existence checks for the cookies and users files.
  `--test-user` and `--retry` still need a readable cookies file once they make API calls.

## Checking batching and DB behavior

- Permanent-failure pre-checks must go through `DatabaseManager.get_permanent_failures_batch()`; per-user `is_permanent_failure()` calls inside a loop are an N+1 pattern (see `patterns/anti-patterns.md`).
- Inspect the SQLite file directly when verifying writes.
  Tables are `block_history` (unique on `user_id`; columns include `status`, `response_code`, `error_message`, `retry_count`, `user_status`) and `process_log` (one row per session).

```bash
sqlite3 block_history.db "SELECT status, COUNT(*) FROM block_history GROUP BY status;"
sqlite3 block_history.db "SELECT user_status, COUNT(*) FROM block_history WHERE status='failed' GROUP BY user_status;"
```

## Writing tests (if you add them)

- Mock `requests` (the API layer uses `requests.get/post` directly) instead of hitting Twitter.
- Use a temporary SQLite file per test (`DatabaseManager(db_file)` creates the schema on construction).
- Do not commit real cookies or real user data as fixtures.

## Pre-merge checklist

- [ ] `python3 -m py_compile twitter_blocker/*.py` passes
- [ ] Behavior verified with `--test-user <name> --debug` (or `--stats` for read-only changes)
- [ ] No credentials or personal data in code, logs or fixtures
- [ ] No per-item DB/API calls introduced inside loops
- [ ] `README.md`, `examples.md` and `AGENTS.md` updated if a CLI flag, module or operational limit changed (see "Documentation" in `AGENTS.md`)
