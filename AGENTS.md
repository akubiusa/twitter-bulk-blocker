# AGENTS.md

Guidance for AI coding agents and contributors. `CLAUDE.md` imports this file, and `.github/copilot-instructions.md` adds the review checklist.

## Language

- All deliverables are written in **English**: commit messages, PR/Issue titles and bodies, review comments, code comments and docstrings, and documentation (`README.md`, `AGENTS.md`, `.claude/**/*.md`, etc.).
- Exceptions (keep as is): the tool's Japanese runtime output (see below), quotations, technical identifiers, generated files, and external source text.
- Runtime output (progress, errors, statistics, `--help`) is currently Japanese and is kept: the scripts under `.claude/` parse it (for example `全対象ユーザー:` and `ブロック済み:` from `--stats`, `認証エラー検出` from the logs). Do not translate or reword those strings without updating every script that matches them. New messages should be English.
- Do not rewrite Git history to change the language of past commits.

## Overview

`twitter_blocker` is a Python CLI (`python3 -m twitter_blocker`) that blocks a list of Twitter/X users with a logged-in browser's cookies. It looks users up through the GraphQL API, blocks them through the REST API, and records results in SQLite so runs can be resumed. Lookups are cached on disk (lookups / profiles / relationships, 30-day TTL). It runs standalone or in Docker.

## Commands

```bash
pip install -r requirements.txt                  # requests, pytz
export CACHE_DIR=./cache                         # outside Docker: runs past argument parsing create it; default /data/cache
python3 -m py_compile twitter_blocker/*.py       # syntax check (the only local quality gate)
python3 -m twitter_blocker --help                # list options
python3 -m twitter_blocker --stats               # statistics only; changes nothing
python3 -m twitter_blocker --debug --test-user <name>   # look up one user, never blocks
python3 -m twitter_blocker --all --auto-retry    # full run (real blocks)
docker build -t twitter-blocker .
docker run --rm -v "$(pwd)/data:/data" twitter-blocker --stats
```

Running without `--all` is **not** a dry run: it blocks the first 5 remaining users. Do not run the tool against a real account unless the task requires it.

There is no committed test suite and CI does not lint or test. `.github/workflows/copilot-setup-steps.yml` installs `black`, `flake8`, `mypy` and `pytest` for the Copilot agent, but nothing enforces them. Do not claim tests pass; verify behavior with `--debug --test-user` or against a throwaway users file, cookie file and `--db`.

## Structure

- `twitter_blocker/__main__.py`: argparse CLI and run modes. Option defaults come from `TWITTER_COOKIES_PATH`, `TWITTER_USERS_FILE`, `TWITTER_BLOCK_DB` and `CACHE_DIR`.
- `api.py`: `TwitterAPI`: GraphQL lookups, REST block call, file cache, request headers, rate-limit and auth-error recovery.
- `manager.py`: `BulkBlockManager`: target selection, batches of 50, safety checks, retries, session records.
- `database.py`: `DatabaseManager`: SQLite tables `block_history` and `process_log`, failure queries.
- `config.py`: users-file schema (`{"format": "screen_name" | "user_id", "users": [...]}`) and cookie loading.
- `retry.py`: failure classification (permanent vs. temporary) and adaptive backoff.
- `stats.py`, `error_analytics.py`, `performance_monitor.py`, `user_status_monitor.py`: statistics and analytics. `version.py`: version resolution.
- `Dockerfile`: Python image, runs as UID 1000 with defaults pointing at `/data/...`.
- `.claude/`: Claude Code slash commands and docs for operating the production deployment through the `Cinnamon` SSH alias. Read the relevant file under `.claude/` only when the task needs it (`guides/`, `patterns/`, `workflows/`, `troubleshooting/`, `operations/`, `commands/`).

## Conventions

- Python: `snake_case` functions and variables, `PascalCase` classes, 4-space indent. Keep docstrings and comments in English and focused on intent, units and constraints.
- Batch database and API access; avoid per-user calls inside loops (for example use `DatabaseManager.get_permanent_failures_batch`).
- Permanent user states (`suspended`, `not_found`, `deactivated`) must not be retried; `unavailable` and retryable HTTP codes are (`retry.py`).
- `DatabaseManager` opens a connection per call. Most methods close it with `conn.close()`; a few (`is_permanent_failure`, `get_permanent_failure_info`, `get_permanent_failures_batch`) use only `with sqlite3.connect(...)`, which commits or rolls back but does not close. Close connections explicitly, in `try`/`finally` or with `contextlib.closing`, when adding or changing methods.
- Monitoring scripts under `.claude/`: keep one version of each script and add options instead of "fast" or "optimized" copies.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/) and branches follow [Conventional Branch](https://conventional-branch.github.io) short form (`feat/...`, `fix/...`).
- Prefer adding commits to an open PR that touches the same area over opening a new one.
- Do not commit to Renovate PRs.

## Production access

The production host is reached only with `ssh Cinnamon` (the SSH config alias); the raw hostname and IP do not work. See `.claude/cinnamon-connection.md`.

## Documentation

- Adding or renaming a CLI option: update `README.md` and `examples.md`.
- Adding or removing a module under `twitter_blocker/`: update "Structure" here and "Project layout" in `README.md`.
- Changing a documented runtime string that `.claude/` scripts match: update the scripts and `.claude/` docs together.

## Security

- Never commit `cookies.json`, users lists, `*.db` files or any credential; they are git-ignored. Keep them in the data directory.
- Never log cookie values or other credentials.
- Respect rate limits. Users you follow or who follow you are skipped, and a user already recorded as blocked is not blocked again; do not weaken these checks.
