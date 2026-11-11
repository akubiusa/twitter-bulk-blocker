Test the given feature before it is merged.

Feature: $ARGUMENTS

The repository has no committed test suite, so verification is a syntax check plus runs of the CLI.
Do not report tests as passing unless you ran them.

1. Syntax: `python3 -m py_compile twitter_blocker/*.py`.
2. Static checks: run `mypy`, `flake8` or `black --check` only if they are installed, and say so if they are not.
3. Functional run with the real API (needs `cookies.json` and a users file):
   - single user: `python3 -m twitter_blocker --test-user <name> --debug`
   - small batch: `python3 -m twitter_blocker` (without `--all` it processes only the first 5 users); with `--all`, `--max-users N` caps the run; both perform real blocks for the processed users, so use a throwaway users file
   - statistics: `python3 -m twitter_blocker --stats`
4. For the changed code path, exercise normal, error and boundary cases (for example suspended, not-found and protected accounts, and a rate-limit response) and read the log output.
5. Use a scratch copy of the database and cache (`--db` / `TWITTER_BLOCK_DB`, `--cache-dir` / `CACHE_DIR`) so production data is untouched, and delete it afterwards.

Report PASS/FAIL per check with the command and its output, any problems found, and suggested fixes.
