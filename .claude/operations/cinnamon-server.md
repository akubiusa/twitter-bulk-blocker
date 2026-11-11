# Cinnamon server operations

The Cinnamon server runs one Twitter Bulk Blocker container per Twitter account via Docker Compose.

- Access: `ssh Cinnamon` (see `../cinnamon-connection.md`)
- Project directory: `/mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users`
- Container names: `bulk-block-users-<service>-1`

All commands below assume the project directory; abbreviate it as `$P`:

```bash
P=/mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users
ssh Cinnamon "cd $P && docker compose ps"
```

## Services and target lists

| Service | Target list |
|---|---|
| `book000` | promoted_and_blueverified.json |
| `book000_vrc` | promoted_only.json |
| `ihc_amot` | promoted_only.json |
| `tomachi_priv` | promoted_and_blueverified.json |
| `authorizedkey` | promoted_and_blueverified.json |
| `tomarabbit` | promoted_and_blueverified.json |

## Monitoring commands

- `/check-cinnamon` runs `.claude/commands/check-cinnamon.md`.
- `/restart-service [service_name]` restarts one service, or all services when no name is given.
- `.claude/cinnamon-logs-ai-optimized.sh` prints a structured analysis for Claude Code to act on.
- `.claude/cinnamon-monitor-suite.sh [mode]` is a wrapper. The modes `basic`, `quick`, `emergency` and `ai` work. `advanced`, `trend` and `realtime` call `cinnamon-logs-advanced.sh`, `cinnamon-trend-analyzer.sh` and `cinnamon-realtime-monitor.sh`, which do not exist in this repository.

### Output of `cinnamon-logs-ai-optimized.sh`

```
SECTION_START: <name>
FINDING: severity=<CRITICAL|WARNING|INFO|OK> category=<cat> message="..."
  DETAILS: ...
  RECOMMENDED_ACTION: ...
SECTION_END: <name>
```

The script ends with `OVERALL_STATUS` (`CRITICAL`, `WARNING`, `ATTENTION` or `HEALTHY`), `TOTAL_FINDINGS` and `ACTIONABLE_ITEMS` (`YES` when a `KeyError ... error_message` was found in the logs, otherwise `MAINTENANCE_ONLY`).

### Detection patterns

| Section | Detects | Response |
|---|---|---|
| `CODE_ANALYSIS_RECOMMENDATIONS` | `KeyError.*error_message` in the logs (CRITICAL). The recommended fix is a guarded access such as `failure_info.get("key", default) if failure_info else default`, which `manager.py` already uses. The line numbers the script prints (402-403, 493) are outdated | Check that the running image is current; update it if not |
| `AUTHENTICATION_STATUS` | Per service, in the last 200 log lines: more than 5 matches of `認証エラー`, `Authentication.*failed`, `401` or `Could not authenticate` is CRITICAL, 1-5 is WARNING | Refresh that service's cookies |
| `PERFORMANCE_ANALYSIS` | Per-service errors versus successful blocks | Review the service configuration or restart it |

## Daily checks

```bash
# container state
ssh Cinnamon "cd $P && docker compose ps"

# most frequent error lines
ssh Cinnamon "cd $P && docker compose logs --tail 1000 | grep -E '(エラー|error|failed|401|403|429|500)' | sort | uniq -c | sort -nr | head -10"

# recent activity per service
for service in book000 book000_vrc ihc_amot tomachi_priv authorizedkey tomarabbit; do
    echo "=== $service ==="
    ssh Cinnamon "cd $P && docker compose logs $service --tail 50 | grep -E '(ブロック成功|スキップ|エラー)' | tail -5"
done
```

Reading the results:

- Urgent: all containers stopped, or continuous 401 errors.
- Watch: a sudden rise in 403 errors, or one service stopping unexpectedly.
- Normal: 404 errors (deleted accounts) and occasional rate limits.

## Error handling

### 401 (authentication)

1. Confirm the account's cookie file exists: `ssh Cinnamon "ls -la /mnt/hdd/cinnamon/twitter-chrome/userdata/{account_name}/cookies.json"`
2. Log in to the account again in Chrome, export a fresh `cookies.json`, and restart the service.

### 403

```bash
ssh Cinnamon "cd $P && docker compose logs --tail 200 | grep -A10 -B5 'Status Code: 403'"
# which services are affected
ssh Cinnamon "cd $P && docker compose logs --tail 500 | grep -E '403.*(authorizedkey|book000|tomachi)'"
```

### Rate limits

```bash
ssh Cinnamon "cd $P && docker compose logs --tail 200 | grep -E 'Rate Limit:' | tail -10"
```

## Emergency operations

```bash
ssh Cinnamon "cd $P && docker compose down"                    # stop everything
ssh Cinnamon "cd $P && docker compose up -d"                   # start everything
ssh Cinnamon "cd $P && docker compose restart {service_name}"  # restart one service
```

## Escalation

Escalate immediately when:

- all services have been down for 30 minutes or more;
- authentication errors persist for an hour or more;
- anything security-related looks wrong.

Keep monitoring for transient 403 errors, a single service pausing, or waiting caused by rate limits.

## Periodic maintenance

- Weekly: check log rotation, disk space and performance statistics.
- Monthly: check cookie expiry and whether a newer Docker image is available.
