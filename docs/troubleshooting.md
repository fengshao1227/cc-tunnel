# Troubleshooting

Start with `cc-tunnel check` in the project directory. It walks the chain in
order: mapping, git freshness, ssh, the remote agent, then an MCP `initialize`
sent from the remote stub through the wrapper, the tunnel, your key, the router
and the server. Whichever step fails first is where to look.

(Agents get the same material as the `cc-tunnel-doctor` skill.)

## The agent has no `workspace_*` tools

MCP configuration is read when the agent process starts. After
`cc-tunnel remote-setup`, or any MCP change, start a new session. On the remote
host, `claude mcp list` should list `cc-tunnel-workspace` as connected.

## `unmapped remote directory`

The session runs in a remote directory no mapping covers. Run `cc-tunnel map`
in the project root locally, and start sessions with `cc-tunnel` from inside it.

## Connection refused to `127.0.0.1:<tunnel port>` on the remote

The tunnel is down.

- `cc-tunnel tunnel status` and `cc-tunnel tunnel logs`.
- launchd restarts it within ~15 s, so a tunnel that stays down is failing
  repeatedly. The usual causes: the tunnel key is not authorized for the
  tunnel account, another machine already holds that tunnel port, or
  `AllowTcpForwarding` is off on the remote.
- Remote Login must be on locally.

## `Permission denied (publickey)` from the remote to the local machine

`cc-tunnel_mac` is not authorized locally. Re-run `cc-tunnel remote-setup` and
accept the prompt, or add the line it prints to `~/.ssh/authorized_keys`.

## ssh exits 255, or hangs

`cc-tunnel` retries a 255 three times, then tells you which of two cases it is:

- **unreachable**: no TCP connection, or no SSH banner. That is a network,
  firewall or host-down problem.
- **wedged**: sshd answers and authenticates, but no session starts. The host
  is out of CPU, or stuck in a shutdown. A graceful reboot of a host in that
  state tends to hang as well; use the provider console's force reset.

Do not lower the keepalives below `ServerAliveInterval 15` ×
`ServerAliveCountMax 8`. One multiplexed connection carries every command and
rsync. At 10 s × 3, a briefly overloaded server had a running sync cut off with
`unexpected end of file`.

## A stale multiplexed connection

```bash
ssh -O exit -o ControlPath=$HOME/.ssh/cc-tunnel-cm/%C <host>
```

Do not `rm` the socket: that leaves the master process running with nothing
pointing at it.

## `env: node: No such file or directory`

A non-interactive ssh session has a minimal PATH. `remote-setup` records where
your node toolchain lives; re-run it after installing or moving node.

## git: `could not read Username ... Device not configured`

An https remote cannot prompt over a non-interactive session. Until you fix
it, `git fetch` fails and `origin/*` keeps an old value, so "0 behind" is
meaningless. `cc-tunnel check` flags it as `[fetch failed: counts may be
stale]`. Switch the remote to ssh:

```bash
git remote set-url origin git@github.com:<owner>/<repo>.git
```

## Every ssh command takes seconds

Measured on the author's setup, repeated `ssh host true` went from a median of
2.98 s to 0.41 s, and the spread from 0.7–5.3 s down to 0.43–0.45 s. It took
two fixes, and neither was enough alone:

1. **Connection reuse.** cc-tunnel multiplexes its own calls. For your own ssh
   to the same host, add `ControlMaster auto`, `ControlPath ~/.ssh/cm-%C` and
   `ControlPersist 10m` to its `Host` block. Alone, this cut the median to
   ~1.7 s but left the jitter.
2. **Keeping ssh out of a local TUN-mode proxy** (Clash, sing-box and others).
   Such a proxy pulls every connection through a userspace TCP stack. Check
   with `route -n get <host>`: an interface named `utun…` means the
   connection is captured. Bind ssh to the physical interface:

   ```bash
   # ~/.config/cc-tunnel/config - used by both cc-tunnel and the tunnel
   CC_TUNNEL_SSH_OPTS="-o BindInterface=en0"
   ```

   or put `BindInterface en0` in your own `Host` block. The proxy's own
   exclusion settings (`route-exclude-address`) did not take effect in
   testing, and TUN settings that a proxy GUI manages get rewritten when it
   restarts. Binding at the socket is what worked.

## `cc-tunnel session` says there are no sessions

It reads `~/.claude/projects/<encoded remote root>/` on the remote. Sessions
started outside the mapped directory are recorded under a different name. Start
them with `cc-tunnel` from the project.

## `pgrep -f` reports a tunnel that is not there

`pgrep -f` matches its own command line, and any shell running the same text.
Look at real ssh processes instead (`pgrep -x ssh`, then each one's arguments),
which is what `cc-tunnel tunnel status` does.
