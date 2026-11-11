# check-cinnamon performance notes

The `check-cinnamon-*` scripts open one `ssh Cinnamon ...` connection per query, so a full run (`--detailed`) takes a while.
The metrics module is the script `check-cinnamon-performance` (see `check-cinnamon.md`); this file only covers how to keep the checks fast.

## Speeding up ssh

Batch several commands into one connection:

```bash
ssh Cinnamon '
docker ps
docker logs <container1> --since 10m
docker logs <container2> --since 10m
'
```

Reuse a connection across calls with a control master:

```bash
SSH_OPTS="-o ControlMaster=auto -o ControlPath=/tmp/ssh-%r@%h:%p -o ControlPersist=30s"
ssh $SSH_OPTS Cinnamon "command1"
ssh $SSH_OPTS Cinnamon "command2"   # reuses the existing connection
```

## Choosing a scope

- Quick look: `check-cinnamon` (version, containers, 403 summary).
- Targeted question: `check-cinnamon --module <name>`.
- Full pass: `check-cinnamon --detailed`.
