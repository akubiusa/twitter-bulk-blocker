# Connecting to the Cinnamon server

Always connect with the ssh alias:

```bash
ssh Cinnamon
```

Do not use a raw IP address or a guessed hostname or user name; the alias carries the correct host, user, port and key.

Check that the alias exists:

```bash
grep -A 10 "Host Cinnamon" ~/.ssh/config
```

Project directory on the server (used by the monitoring scripts):

```bash
ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose ps"
```

If the connection fails:

1. Confirm the `Host Cinnamon` entry (see above).
2. Run `ssh -v Cinnamon` and read the verbose output.
3. Check the VPN or network state.

When writing a script that talks to the server, use `ssh Cinnamon` everywhere and fail early with a clear message if the connection does not work:

```bash
if ! ssh Cinnamon "true" >/dev/null 2>&1; then
    echo "Error: cannot connect to Cinnamon server (check ~/.ssh/config, use: ssh Cinnamon)"
    exit 1
fi
```
