---
name: cc-tunnel-doctor
description: Diagnose a broken cc-tunnel setup - workspace_* MCP tools missing, disconnected or timing out, the reverse tunnel down, ssh failing with status 255 or hanging, the wrong project mapped, a git checkout that claims to be current but is not, or ssh that is unexpectedly slow. Use when `cc-tunnel` commands fail or the workspace tools error.
---

# Diagnosing cc-tunnel

Start with `cc-tunnel check`, run on the local machine in the project's
directory. It tests the mapping, ssh, the remote agent, the tunnel and the
workspace MCP server end to end, and says which one failed. Then match the
symptom below.

## Workspace tools are missing from the session

MCP configuration is read once, when the agent process starts. After
`cc-tunnel remote-setup`, or any MCP change, quit and start a new session. On
the remote host, `claude mcp list` should show `cc-tunnel-workspace` connected.

## "unmapped remote directory"

The session runs in a remote directory that no line of
`~/.config/cc-tunnel/projects.conf` covers. Run `cc-tunnel map` in the project
root on the local machine, then start the session with `cc-tunnel` from there.

## Connection refused on 127.0.0.1:<tunnel port> (from the remote side)

The reverse tunnel is down. On the local machine:

- `cc-tunnel tunnel status`, then `cc-tunnel tunnel logs`.
- launchd restarts the tunnel within about 15 s of it dying. If it keeps
  failing, read the logs. The usual causes are the remote host refusing the
  tunnel key, or another tunnel already holding that port: two machines cannot
  share one tunnel port.
- Remote Login (sshd) must be on: System Settings > General > Sharing.

## Permission denied (publickey) from the remote side

The remote host's `cc-tunnel_mac` key is not in the local
`~/.ssh/authorized_keys`. Re-run `cc-tunnel remote-setup` and accept the
prompt. Its line is restricted to `from="127.0.0.1,::1"`, which is why the
key only works through the tunnel.

## ssh exits with 255, or hangs

`cc-tunnel` retries 255 three times, then says which of two cases it is. They
need opposite responses:

- **Unreachable**: no TCP connection, or no SSH banner. That is a network,
  firewall or host-down question.
- **Wedged**: sshd answers and authenticates, but no session ever starts. The
  host is out of CPU, or stuck in a shutdown. A graceful reboot of a host in
  that state usually hangs too; use the provider's console force reset.

## Never tighten the keepalives

The connections are multiplexed (ControlMaster), so one ssh process carries
every command and rsync. `ServerAliveInterval 15` × `ServerAliveCountMax 8`
(120 s) is deliberate. At 10 s × 3, a loaded server that went quiet for half a
minute killed a running sync mid-transfer.

## A stale multiplexed connection

Close it explicitly: `ssh -O exit -o ControlPath=~/.ssh/cc-tunnel-cm/%C <host>`.
Do not `rm` the socket glob, because that strands the master process instead
of stopping it.

## "env: node: No such file or directory" from codegraph or fast-context

A non-interactive ssh session has a minimal PATH. The wrappers export
`CC_TUNNEL_MAC_PATH`, which `cc-tunnel remote-setup` records from the local
machine. Re-run it after installing or moving node.

## git says "could not read Username ... Device not configured"

That is an https remote with nothing to prompt on. Switch it to ssh:
`git remote set-url origin git@github.com:<owner>/<repo>.git`. Until you do,
`fetch` fails and "0 behind" means nothing.

## Every ssh command takes seconds

Two independent causes, and fixing both is what got repeated commands from
about 3 s to about 0.4 s:

1. **No connection reuse.** `cc-tunnel` multiplexes its own calls. For your
   own `ssh` to the same host, add `ControlMaster auto`,
   `ControlPath ~/.ssh/cm-%C` and `ControlPersist 10m` to its Host block.
2. **A local proxy in TUN mode** (Clash, sing-box and the like) captures the
   traffic and pushes it through a userspace TCP stack. Check with
   `route -n get <host>`: an interface named `utun*` means it is captured. Bind
   ssh to the real interface, with `CC_TUNNEL_SSH_OPTS="-o BindInterface=en0"`
   in the config (used by both `cc-tunnel` and the tunnel), or `BindInterface`
   in your own Host block. Proxy-side exclusions such as
   `route-exclude-address` were not reliable in testing.

## `pgrep -f` says the tunnel is up when it is not

`pgrep -f` matches its own command line, and any shell running the same
string. Look for real ssh processes: `pgrep -x ssh`, then inspect each one's
arguments. `cc-tunnel-link` does exactly this.
