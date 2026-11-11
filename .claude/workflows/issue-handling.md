# Issue Handling Workflow

Flow for "handle issue #N": read the issue and all its comments, branch, implement, verify, commit, open a PR that closes the issue.
The global `/issue-pr <number>` skill automates this; this file records the repo-specific rules it must respect.

## 1. Collect the full context

```bash
gh issue view N --json title,body,author,labels,milestone,assignees,state
gh issue view N --json comments --jq '.comments[] | {author: .author.login, createdAt, body}'
gh pr list --search "N in:body" --state all      # related or earlier PRs
```

- Read the comments in chronological order: they often change the requirements or add constraints, and the latest one wins.
- Check labels for category and priority, and look for linked issues.

## 2. Prefer an existing PR over a new one

If an open PR touches the same files or functional area, or the issue is a related bug fix, add commits to that PR instead of opening another one (see `AGENTS.md`).
Open a new PR only for an independent change.

## 3. Branch

Conventional Branch short form, optionally with the issue number: `<type>/<issue>-<short-description>`.

```bash
git checkout -b fix/25-permanent-failure-detection
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

## 4. Implement

- Break the issue into tasks (3 or more steps: use the task list) and keep each change scoped to what the issue asks for.
- Follow the conventions in `AGENTS.md`: batch all DB/API access (no N+1), pre-check permanent failures with `get_permanent_failures_batch`, use context managers for SQLite connections, keep a single version of each monitoring script.
- When a CLI flag is added or renamed, update `README.md` and `examples.md`; when a module is added or removed, update "Structure" in `AGENTS.md` and "Project layout" in `README.md`.

## 5. Verify

There is no committed test suite (see `quality/testing-guide.md`).

```bash
python3 -m py_compile twitter_blocker/*.py
python3 -m twitter_blocker --test-user <name> --debug     # lookup only, no block
python3 -m twitter_blocker --stats
```

Checklist:
- [ ] Every requirement in the issue body and in the comments is covered
- [ ] Existing flows are unaffected (retry handling, cache, DB schema)
- [ ] Error handling and rate-limit behavior unchanged or deliberately changed
- [ ] No credentials or personal data in code, logs or fixtures
- [ ] Behavior verified as above, and the PR says exactly what was run

## 6. Commit

Conventional Commits with an English description: `<type>(<scope>): <description>`; mention the issue in the body or footer (`Closes #N`).

```
fix(database): skip API lookups for permanently failed users

Pre-check permanent failures with one batched query per batch instead of
calling the API for suspended or deactivated accounts again.

Closes #25
```

Push with `git push -u origin <branch>` (SSH remote).

## 7. Pull request

- Title: Conventional Commits format, in English.
- Body: summary of the change, what was verified (commands actually run and their result), and `Closes #N`.
  Mention deviations from the issue or requirement changes taken from comments.
- Do not state performance numbers or test results that were not measured.

## Per-type notes

| Issue type | Extra checks |
|---|---|
| Bug fix | Identify and fix the root cause, check sibling callers of the changed function, note how the fix was verified |
| Feature | Requirement fully implemented, consistent with existing flags/modules, docs updated |
| Performance | Measure before and after on comparable data and report the numbers; keep behavior identical |
| Docs | Statements checked against the code, links valid |
