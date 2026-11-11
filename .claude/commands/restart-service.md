Restart services on the Cinnamon production host.

Arguments: `$ARGUMENTS`
- With arguments: restart only those services.
- Without: restart all services.

Services: book000, book000_vrc, ihc_amot, tomachi_priv, authorizedkey, tomarabbit

Run from the compose directory on the host (`/mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users`, see `.claude/cinnamon-connection.md`):

1. Restart: `ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose restart $ARGUMENTS"` (omit `$ARGUMENTS` to restart everything).
2. Verify:
   - `ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose ps"`
   - `ssh Cinnamon "docker logs --tail 10 bulk-block-users-<service>-1"`
3. Report success or failure; analyze any error and propose next steps.
