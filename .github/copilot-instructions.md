# Copilot review instructions

Follow `AGENTS.md` at the repository root for the project overview, structure and conventions. Write review comments in English.

## Review checklist

- **Batching:** no per-user database or API call inside a loop when a batch method exists (for example `get_permanent_failures_batch`).
- **Failure classification (`retry.py`):** permanent states (`suspended`, `not_found`, `deactivated`) are never retried; `unavailable` and the retryable HTTP codes are. Flag new handling that gets this wrong.
- **Safety invariants:** users you follow or who follow you are skipped, and a user already recorded as blocked is not blocked again. Flag changes that weaken either, or that remove the request delay or rate-limit waits.
- **Resources:** SQLite connections are closed on every path, including exceptions.
- **Secrets and privacy:** no `cookies.json`, tokens, user lists or databases in the diff, and no credentials or cookie values in logs.
- **Docs:** CLI option changes update `README.md` and `examples.md`; module changes update the layout in `README.md` and `AGENTS.md`.

## Language

All deliverables (code comments, docstrings, docs, commit messages, PR text) are English. The tool's Japanese runtime output is intentional because `.claude/` scripts parse it; do not flag it, and flag translations of it that do not update those scripts.

## Do not flag

- Japanese runtime strings and emoji in CLI output.
- Scripts under `.claude/` (operations helpers) for application conventions.
- The absence of tests: there is no test suite and CI does not run one.
- The default users-file name `video_misuse_detecteds.json`.
