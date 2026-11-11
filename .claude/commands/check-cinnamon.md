# check-cinnamon

Monitoring entry point for the Cinnamon production host (ssh alias `Cinnamon`, see `../cinnamon-connection.md`).
`check-cinnamon` is a thin dispatcher: the basic check runs the brief version, errors and container modules, and every other analysis is a separate script that can be run on its own.
Run all commands from the repository root.

## Usage

```bash
.claude/commands/check-cinnamon                      # basic check: version, containers, 403 errors, recommended action
.claude/commands/check-cinnamon --detailed           # basic check plus completion, performance --compare, account analysis
.claude/commands/check-cinnamon --errors-only        # 403 error analysis only
.claude/commands/check-cinnamon --module <name>      # one module; repeat --module to run several
```

Short options: `-d`, `-e`, `-m`, `-h`.
`check-cinnamon` itself has no `--brief` option; `--brief` exists only on the individual scripts that list it below.

## Modules

| `--module` | Script | Options | What it reports |
|---|---|---|---|
| `version` | `check-cinnamon-version` | `--brief` | Running version per `python3 -m twitter_blocker --version`, latest GitHub release, update recommendation (a leading `v` is ignored when comparing) |
| `container` | `check-cinnamon-containers` | `--brief` | Running/stopped containers, health, uptime |
| `errors` | `check-cinnamon-errors` | `--brief` | 403 errors per service over 10 minutes: CRITICAL >= 50, HIGH >= 20, MEDIUM >= 5, otherwise LOW |
| `completion` | `check-cinnamon-completion` | none | `--stats` output per service (total targets, blocked, permanent failures, effective completion rate) |
| `health` | `check-cinnamon-health` | none | Authentication-error counts over 5m/1h/6h/24h |
| `container-health` | `check-cinnamon-container-health` | none | Container health and restart recommendation |
| `rate-limit` | `check-cinnamon-rate-limit-monitor` | none | Rate-limit waits detected in recent logs and predicted resume time |
| `performance` | `check-cinnamon-performance` | `--brief`, `--compare` | 24h processed/error counts and success rate per account; `--compare` diffs against the previous run. History is kept in `/tmp/cinnamon-performance-history.json` (last 100 entries) |
| `accounts` | `check-cinnamon-account-analysis` | `--brief` | Per-account risk level (HIGH/MEDIUM/LOW), primary error type (AUTH/RATE_LIMIT/NETWORK/GENERAL) and suggested action |
| `processing` | `check-cinnamon-processing-status` | none | Latest errors, last success and cookie log lines per account, 1h attempt/success/403 counts, stall detection |

Two scripts are not wired into the dispatcher and are run directly: `check-cinnamon-health-score` (score out of 100 from 1/5/10/30-minute 403 counts) and `check-cinnamon-trend` (improving/worsening 403 trend).

## Recommended flow

1. `check-cinnamon` for an overview.
2. If the recommended action reports 403 errors, run `check-cinnamon --errors-only`, then `--module health`, `--module rate-limit` or `--module accounts` depending on the error type.
3. Use `check-cinnamon --detailed` for a full pass; save it with `check-cinnamon --detailed 2>&1 | tee cinnamon-$(date +%Y%m%d-%H%M).log` if it needs to be kept.

The recommended action at the end of the basic check is based on the total 403 count over 10 minutes across all containers: > 50 CRITICAL, > 20 WARNING, > 5 MEDIUM, otherwise GOOD.

## Troubleshooting

- A module reports "not found" or is not executable: check `ls -la .claude/commands/check-cinnamon-*` and `chmod +x` the script.
- Output is cut off: run the modules one at a time instead of `--detailed`.
