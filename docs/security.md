# Security

## The trust model, plainly

**Whoever controls the agent's account on the remote host can run commands on
your local machine, as you.** `workspace_exec` is a shell by design: builds,
tests and git have to run somewhere, and the point is that they run where the
code is.

So the remote host belongs to your trusted base, the same as a CI runner with
deploy rights:

- Keep it patched, and do not share it with other tenants or other people's
  workloads.
- Run the agent as its own non-root account (`scripts/vps-bootstrap.sh` does).
  root on the remote host can still become that account, which is why the host
  itself must be trusted.
- Log in with keys only.

Everything below limits *how* the remote host reaches you. None of it limits
*what* an agent there can do once it has.

## What each key can do

| Key | From → to | Restrictions |
| --- | --- | --- |
| `cc-tunnel_remote` | local → agent account | none; it is the agent's own login |
| `cc-tunnel_tunnel` | local → tunnel account | `restrict,port-forwarding,command="/bin/false"`; on OpenSSH 7.8+ also `permitlisten="127.0.0.1:<port>"`. No shell, no commands, one loopback listener. |
| `cc-tunnel_mac` | remote → you, through the tunnel | `restrict,from="127.0.0.1,::1"`. No pty, no forwarding, and only from the tunnel's loopback end. |

The tunnel listens on the remote host's loopback only. If `GatewayPorts` were
on, anyone who could reach that host could reach your sshd through it.
`vps-bootstrap.sh` warns if it is.

## What the workspace server refuses

- **Paths outside the mapped root**, after resolving symlinks and `..`. The
  router also refuses a remote path with `.` or `..` segments before it builds
  the local one.
- **Sensitive names**, in the file tools and in search: `.env`, `.env.*`,
  `.git-credentials`, `.netrc`, `.npmrc`, `.pypirc`, `.gitlab-token`,
  `.deploy-keys`, `id_rsa`, `id_ecdsa`, `id_ed25519`. Extend the list with
  `CC_TUNNEL_SENSITIVE`.
- **Overwriting a changed file**, when the caller passes `expected_sha256`.
- **Writes while another session holds the lock.**

This is an accident barrier, not a boundary: `workspace_exec` can `cat` any
file your user can read. It keeps an agent from stumbling into a secret during
ordinary reads and searches. It does not stop one that sets out to read it.

## What crosses to the remote host, and what never does

| Crosses | Never crosses (cc-tunnel copies none of it) |
| --- | --- |
| What the agent reads through the tools, and so the model provider sees, as in any agent setup | The source tree as a whole: there is no mirror |
| Memory files (`*.md` in the project's memory directory) | `.env` files, keys, git credentials |
| `AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md` of a mapped project | Local Claude transcripts: the memory filter syncs `*.md` only |
| Local *paths* in `remote.env` | Browser sessions and cookies |

Do not put secrets in memory or rules files: both are copied to the remote
host by design.

`cc-tunnel session` reads the remote transcript tail over ssh into your terminal
and stores nothing. Transcripts can hold anything that was pasted into a
session, which is why they are kept out of every sync.

## The write lease

`workspace_lock` makes `workspace_write` and `workspace_patch` from *other MCP
sessions* fail until it is released, or until the holder's process exits. It
covers nothing else: `workspace_exec`, your editor, and agents running directly
on the local machine all write without asking. For real parallel work, give
each agent its own `git worktree`.

## Reporting a problem

Open an issue without exploit details and ask for a private channel.
