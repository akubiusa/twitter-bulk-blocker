# Emergency Response Workflow

Use this when a run is misbehaving (repeated auth failures, suspected DB corruption, runaway rate-limit errors, full disk).
On the production host (Cinnamon), run `docker compose` commands through `ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && ..."`; see `.claude/cinnamon-connection.md` and `.claude/operations/cinnamon-server.md`.

Paths in the file commands below (`block_history.db`, `cookies.json`, `cache/`) are relative to the data directory of the instance you are working on.
In production the app runs in Docker and its env vars point at `/data/...` inside the container (`Dockerfile`); the image has no `sqlite3` or `jq`.
The repository does not document where that volume lives on the host (only the cookies source `/mnt/hdd/cinnamon/twitter-chrome/userdata/<account>/cookies.json` appears in `operations/cinnamon-server.md`) or how the DB is mounted: confirm with `docker compose config` / `docker inspect` before touching files, and run `sqlite3`/`jq` on the host against the mounted files.
`python3 -m twitter_blocker ...` commands can be run in the container with `docker compose exec <service> python3 -m twitter_blocker ...` (unverified in this repo; check the compose file).

## 1. Stop the process

```bash
# Docker (production): one container per account/service
docker compose ps
docker compose stop <service>      # or: docker compose down  (all services)

# Standalone
pkill -f "python.*twitter_blocker"
```

Progress is stored in SQLite, so stopping is safe at any time; an interrupted run resumes from the DB.

## 2. Back up before changing anything

Copy the DB, the cookies file and the users file (the cache is rebuildable and optional).
If SQLite is mid-write, copy the `-journal` file along with the DB.

```bash
BACKUP_DIR="emergency_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp block_history.db* cookies.json "$BACKUP_DIR/"
cp <users-file> "$BACKUP_DIR/"     # default name: video_misuse_detecteds.json (--users-file / TWITTER_USERS_FILE)
ls -la "$BACKUP_DIR"
```

Never put `cookies.json` backups anywhere that is committed or shared.

## 3. Diagnose

```bash
df -h; free -m                                        # disk / memory
ls -la block_history.db* cookies.json                 # files present, sizes, ownership
sqlite3 block_history.db "PRAGMA integrity_check;"    # prints "ok" when healthy
python3 -m twitter_blocker --stats                    # DB readable, counts plausible
docker compose logs --tail 200 <service>              # in Docker
```

Look for `認証エラー検出`, `レートリミット検出`, `403エラー…検出`, `緊急クールダウン開始` in the logs.
The tool writes to stdout only; there is no application log file.

## 4. Problem-specific actions

### Database corruption

```bash
sqlite3 block_history.db "PRAGMA integrity_check;"
sqlite3 block_history.db ".recover" | sqlite3 recovered.db     # then inspect recovered.db and swap it in
```

Keep the original corrupt DB and its `-journal` file: move them aside (for example `mv block_history.db block_history.db.corrupt`) instead of deleting or overwriting them.
If recovery fails, restore the latest backup of `block_history.db`.
As a last resort start with a fresh DB (moving the old files aside first): the tool recreates the schema on startup, but all block history is lost and already-blocked users will be looked up and processed again.

### Authentication failure

1. Confirm the file parses: `jq 'length' cookies.json`.
2. Export fresh cookies (`ct0`, `auth_token`) from a logged-in browser and overwrite `cookies.json`.
3. Verify with `python3 -m twitter_blocker --test-user <name> --debug` (lookup only).
4. Restart the service.

A running process that is waiting on a 401 picks up a refreshed cookies file by itself (see `troubleshooting/common-issues.md`).

### Rate-limit or 403 storm

1. Stop the service.
2. Wait at least one 15-minute window before restarting (Twitter's rate-limit windows are 15 minutes; the exact quotas are not documented in this repository).
3. Restart with a larger delay, for example `--delay 5.0`.
   After 20 accumulated 403s the tool itself pauses for 30 minutes (a blocking `time.sleep(1800)`); do not interpret that as a hang.
   Stopping the service during that pause is safe for the DB; `docker stop` may wait the grace period before killing the process (unverified).

### Disk full

```bash
du -sh cache/* block_history.db*
```

The cache is rebuildable: `cache/lookups`, `cache/profiles` and `cache/relationships` can be deleted at the cost of extra GraphQL calls (and therefore rate-limit pressure) on the next run.
Docker logs can also be large: check `docker system df` and the container log size.

## 5. Gradual recovery

Restart in steps and only continue when the previous step is clean:

```bash
python3 -m twitter_blocker --test-user <name> --debug      # 1. lookup works (no block)
python3 -m twitter_blocker --all --max-users 5 --delay 5.0  # 2. small real run
python3 -m twitter_blocker --all --auto-retry               # 3. normal operation
```

Note that `--all --max-users N` really blocks N users, and running without flags blocks the first 5.

## 6. Data consistency check

```bash
sqlite3 block_history.db "
SELECT status, COUNT(*) FROM block_history GROUP BY status;
SELECT user_status, COUNT(*) FROM block_history WHERE status='failed' GROUP BY user_status;
SELECT user_id, COUNT(*) FROM block_history GROUP BY user_id HAVING COUNT(*) > 1;   -- must be empty (UNIQUE user_id)
"
```

## After the incident

- Record what happened, the root cause and the fix in the PR or issue that addresses it.
- If a code change is needed, follow `workflows/issue-handling.md`.
