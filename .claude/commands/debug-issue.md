Investigate and debug the problem described below.

Problem: $ARGUMENTS

1. Understand: symptoms, conditions, frequency, affected scope; collect the relevant logs (production logs via `.claude/cinnamon-logs.sh`); try to reproduce with `python3 -m twitter_blocker --test-user <name> --debug`.
2. Find the root cause: read the relevant code, trace the data flow, check configuration and environment (cookies, users file, cache and database paths).
3. Choose a fix: compare approaches, prefer the smallest change, assess side effects.
4. Implement and verify: apply the fix, run `python3 -m py_compile twitter_blocker/*.py`, and confirm the behavior with a debug run (the repository has no committed test suite).

Report the findings of each step and finish with the concrete fix.
