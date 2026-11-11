# Authentication error monitoring

Authentication errors are analyzed by the `AUTHENTICATION_STATUS` section of `.claude/cinnamon-logs-ai-optimized.sh` (also reachable with `.claude/cinnamon-monitor-suite.sh ai`).

## What it does

- Reads the last 200 lines of `docker compose logs` on the Cinnamon server.
- Matches `認証エラー`, `Authentication.*failed`, `401` and `Could not authenticate`.
- Counts matches per service (`book000`, `book000_vrc`, `ihc_amot`, `tomachi_priv`, `authorizedkey`, `tomarabbit`).
- Reports CRITICAL for more than 5 matches in a service, WARNING for 1-5, and OK when there are none.

## Response

1. Confirm the failing account's cookie file: `/mnt/hdd/cinnamon/twitter-chrome/userdata/{account_name}/cookies.json`.
2. Log in to the account again in Chrome and export a fresh `cookies.json`.
3. Restart the service: `/restart-service <service_name>`, or `ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose restart <service_name>"`.

See `../operations/cinnamon-server.md` for the surrounding operations guide and `../guides/error-handling.md` for error handling in the code.
