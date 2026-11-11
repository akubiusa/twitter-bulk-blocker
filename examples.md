# Examples

Command lines for `python3 -m twitter_blocker`. See [README.md](README.md) for all options. Replace the paths with your own.

> Running without `--all` is not a dry run: it blocks the first 5 remaining users.

## Basic runs

```bash
# Test mode: process the first 5 remaining users
python3 -m twitter_blocker

# Process all remaining users
python3 -m twitter_blocker --all

# Process all remaining users, then retry the failures
python3 -m twitter_blocker --all --auto-retry
```

## Choosing files

```bash
# Absolute paths
python3 -m twitter_blocker --all \
  --cookies /home/user/twitter/cookies.json \
  --users-file /home/user/twitter/block_targets.json \
  --db /home/user/twitter/block_history.db

# Relative paths
python3 -m twitter_blocker --all \
  --cookies ./data/cookies.json \
  --users-file ./data/users.json \
  --db ./data/history.db

# Environment variables
export TWITTER_COOKIES_PATH=/home/user/twitter/cookies.json
export TWITTER_USERS_FILE=/home/user/twitter/users.json
export TWITTER_BLOCK_DB=/home/user/twitter/history.db
export CACHE_DIR=/home/user/twitter/cache
python3 -m twitter_blocker --all --auto-retry
```

## Limits and pacing

```bash
# At most 100 users
python3 -m twitter_blocker --all --max-users 100

# 2 seconds between requests
python3 -m twitter_blocker --all --delay 2.0

# Careful run: 3 seconds between requests, at most 50 users
python3 -m twitter_blocker --all --delay 3.0 --max-users 50

# Retry failed users only
python3 -m twitter_blocker --retry

# Show statistics
python3 -m twitter_blocker --stats
```

## Debugging

```bash
# Look up one user without blocking
python3 -m twitter_blocker --debug --test-user example_user

# Show samples of stored error messages
python3 -m twitter_blocker --debug-errors

# Process at most 5 users with detailed output (this blocks them)
python3 -m twitter_blocker --debug --max-users 5

# Missing cookie file: the tool prints an error and exits with status 1
python3 -m twitter_blocker --all --cookies ./nonexistent.json
```

## Scripting

```bash
#!/bin/bash
# batch_block.sh
export TWITTER_COOKIES_PATH=/home/user/twitter/cookies.json
export TWITTER_USERS_FILE=/home/user/twitter/block_targets.json
export TWITTER_BLOCK_DB=/home/user/twitter/block_history.db
export CACHE_DIR=/home/user/twitter/cache

python3 -m twitter_blocker --stats
python3 -m twitter_blocker --all --auto-retry --delay 1.5
python3 -m twitter_blocker --stats
```

Run it from cron, for example every day at 02:00:

```cron
0 2 * * * cd /path/to/twitter-bulk-blocker && python3 -m twitter_blocker --all --auto-retry >> /var/log/twitter-block.log 2>&1
```

Keep a copy of the database before large runs, for example `cp block_history.db backup/block_history_$(date +%Y%m%d).db`.
