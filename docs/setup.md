# Setup

Two machines:

- **local**: keeps the code. This guide assumes macOS.
- **remote**: runs the agent. Linux with OpenSSH.

Three keys, each with one job:

| Key | Lives on | Logs in as | Can do |
| --- | --- | --- | --- |
| `cc-tunnel_remote` | local | the agent account on the remote | an ordinary login: start sessions, sync memory, run `remote-setup` |
| `cc-tunnel_tunnel` | local | the tunnel account on the remote | open the reverse tunnel, nothing else |
| `cc-tunnel_mac` | remote (made by `remote-setup`) | you, on the local machine, through the tunnel only | run commands (the MCP server); no pty, no forwarding |

## 1. Install locally

```bash
git clone https://github.com/fengshao1227/cc-tunnel && cd cc-tunnel
./install.sh
```

This puts the tools in `~/.local/bin` (`PREFIX=` changes that), the remote
payload and skills in `~/.local/share/cc-tunnel`, a config template in
`~/.config/cc-tunnel/config`, and a launchd job in `~/Library/LaunchAgents`. It
does not start the job, and it never overwrites an existing config.

Install ripgrep if you do not have it: `brew install ripgrep`.

## 2. Make the two local keys

```bash
ssh-keygen -t ed25519 -f ~/.ssh/cc-tunnel_remote -N ''
ssh-keygen -t ed25519 -f ~/.ssh/cc-tunnel_tunnel -N ''
```

A passphrase-less key is what lets launchd hold the tunnel open unattended.
That is why the tunnel key gets an account that can do nothing else.

## 3. Create the remote accounts (once, as root)

Copy `cc-tunnel_remote.pub`, `cc-tunnel_tunnel.pub` and
`scripts/vps-bootstrap.sh` to the remote host, then:

```bash
sudo bash vps-bootstrap.sh --agent-key cc-tunnel_remote.pub --tunnel-key cc-tunnel_tunnel.pub
```

It creates:

- `agent`: an ordinary user with no sudo, and `~/projects` for the stubs.
- `cc-tunnel-link`: no shell, and its key is restricted to
  `restrict,port-forwarding,command="/bin/false"`. On OpenSSH 7.8+ the key is
  also restricted to `permitlisten="127.0.0.1:22022"`, so it can hold that one
  loopback port and nothing else. On older OpenSSH it says so, and the key can
  open other remote forwards too.

`--agent-user`, `--tunnel-user` and `--tunnel-port` change the defaults. It
also warns if `GatewayPorts` would expose the tunnel port beyond loopback, or
if `AllowTcpForwarding` would block the tunnel.

## 4. Install the agent on the remote

As the `agent` user, install Claude Code
(<https://docs.anthropic.com/en/docs/claude-code>) and sign in once
interactively. cc-tunnel starts the agent with `bash -lc`, so wherever the
installer puts `claude` must be on the login PATH.

## 5. Turn on Remote Login locally

System Settings > General > Sharing > Remote Login. Connections from the remote
arrive through the tunnel at `127.0.0.1:22`, so this is how they get in.
Restricting Remote Login to your own user is a good idea.

## 6. Configure

Edit `~/.config/cc-tunnel/config`:

```bash
CC_TUNNEL_REMOTE_HOST=vps.example.com     # or a Host alias from ~/.ssh/config
CC_TUNNEL_REMOTE_USER=agent
CC_TUNNEL_REMOTE_KEY=~/.ssh/cc-tunnel_remote
CC_TUNNEL_TUNNEL_USER=cc-tunnel-link
CC_TUNNEL_TUNNEL_KEY=~/.ssh/cc-tunnel_tunnel
CC_TUNNEL_TUNNEL_PORT=22022
```

If you already reach the host through a `Host` alias in `~/.ssh/config`, set
`CC_TUNNEL_REMOTE_HOST` to the alias and leave the port and key empty. cc-tunnel
only passes options you set, so the alias keeps its own.

## 7. Start the tunnel

```bash
cc-tunnel tunnel start
cc-tunnel tunnel status        # "tunnel  up (ssh pid ..., remote 127.0.0.1:22022 -> here)"
```

launchd restarts it whenever it exits. `cc-tunnel tunnel logs` shows why it did.

## 8. Install the remote side

```bash
cc-tunnel remote-setup                       # add --with-codegraph / --with-fast-context if you use them
```

On the remote this:

- installs the wrappers in `~/.local/share/cc-tunnel/bin`;
- writes `~/.config/cc-tunnel/remote.env`, which holds local *paths* only, no
  secrets;
- generates `~/.ssh/cc-tunnel_mac`;
- puts a `Host cc-tunnel-mac` block at the top of `~/.ssh/config`;
- registers `cc-tunnel-workspace` as a user-scope MCP server;
- adds the `SessionEnd` memory hook;
- adds a short rules block to `~/.claude/CLAUDE.md`;
- copies the skills.

Back on the local machine it then offers to authorize `cc-tunnel_mac`, by
appending one line to `~/.ssh/authorized_keys`:

```text
restrict,from="127.0.0.1,::1" ssh-ed25519 AAAA... cc-tunnel@<remote host>
```

`restrict` takes away pty and forwarding. `from=` makes the key useless except
through the tunnel. Re-run `remote-setup` any time; it is idempotent.

## 9. Use it in a project

```bash
cd ~/code/app
cc-tunnel map                 # ~/code/app -> /home/agent/projects/app (pass a name to choose another)
cc-tunnel check
cc-tunnel                     # or: cc-tunnel -r to resume an earlier session
```

`cc-tunnel check` ends with the one test that matters. It sends an MCP
`initialize` from the remote stub, through the wrapper, the tunnel, your key,
the router and the server, and reports `workspace server answers through the
tunnel` when every link holds.

A mapped root can be one repository, or a directory that holds several. A
mapping for a subdirectory beats one for its parent.

## Updating

```bash
git pull && ./install.sh && cc-tunnel remote-setup
```

Then restart running agent sessions: MCP configuration is read only when the
process starts.

## A second local machine

Each local machine needs its own tunnel port (`CC_TUNNEL_TUNNEL_PORT=22023`).
Two machines cannot share a port. The remote side's `cc-tunnel-mac` alias
points at one port, so decide which machine is the one that holds the code.
Edits made on another machine are invisible to the agent until they reach that
machine.

## Linux as the local machine

Everything except the launchd job is portable. Run `cc-tunnel-link` under a
systemd user unit with `Restart=always`, and use `cc-tunnel-link` itself in
place of `cc-tunnel tunnel start`.

## Removing it

Locally: `./install.sh --uninstall`. Then delete the `cc-tunnel@` line from
`~/.ssh/authorized_keys` and, if you like, `~/.config/cc-tunnel`.

On the remote, as the agent user:

```bash
claude mcp remove --scope user cc-tunnel-workspace
rm -rf ~/.local/share/cc-tunnel ~/.config/cc-tunnel ~/.claude/skills/cc-tunnel-* ~/.ssh/cc-tunnel_mac*
```

Then delete the `# >>> cc-tunnel >>>` blocks from `~/.ssh/config` and
`~/.claude/CLAUDE.md`, and the `cc-tunnel-sync-home` entry from the `SessionEnd`
hooks in `~/.claude/settings.json`. A backup taken before cc-tunnel first edited
it is in `settings.json.cc-tunnel-bak`.
