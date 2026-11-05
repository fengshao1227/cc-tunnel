# MCP servers

Which MCP servers a cc-tunnel setup runs, where each one runs, and how it is
configured.

The rule of thumb: **anything that reads the code runs on the local machine,
through the tunnel. Anything that does not can run on the remote host
directly.**

| Server | Runs on | Purpose | Registered by |
| --- | --- | --- | --- |
| `cc-tunnel-workspace` | local, via tunnel | read, find, patch, write, exec, jobs, lock | `cc-tunnel remote-setup` (required) |
| `cc-tunnel-codegraph` | local, via tunnel | structure, callers, blast radius | `remote-setup --with-codegraph` |
| `cc-tunnel-fast-context` | local, via tunnel | natural-language code search | `remote-setup --with-fast-context` |
| docs, web search, ... | remote | library docs, web search | you (see below) |

## cc-tunnel-workspace (required)

Registered at **user scope**, so every project on the remote host has it. The
wrapper passes the session's working directory to the router on the local
machine, and the router picks the project. One registration covers every
mapped project.

```bash
claude mcp add --scope user cc-tunnel-workspace -- ~/.local/share/cc-tunnel/bin/cc-tunnel-workspace
claude mcp list        # cc-tunnel-workspace ... Connected
```

Its tools:

| Tool | Like | Notes |
| --- | --- | --- |
| `workspace_status` | — | Local absolute root, git state of each repo in it, lock holder. Call first. |
| `workspace_read` | Read | Numbered lines plus a 16-char sha256 prefix. Without a range, the first 600 lines. |
| `workspace_find` | Grep / Glob | ripgrep. `output_mode`, `glob`, `type`, `context`; `files_only` matches names. |
| `workspace_patch` | Edit | `old_text` must be unique unless `replace_all`. Applied to the file's current bytes. |
| `workspace_write` | Write | Pass `expected_sha256` to refuse overwriting a concurrent change. |
| `workspace_exec` | Bash | Runs locally. `background: true` for anything over a minute. |
| `workspace_job` | — | `wait_seconds` (≤600) instead of polling; `kill`. |
| `workspace_lock` / `workspace_unlock` | — | A write lease: other sessions' `write`/`patch` are refused while it is held. |

### Other agents

Any MCP client that can start a stdio server can use it. The command is the
wrapper, and it must start in the project's stub directory. Generic JSON:

```json
{
  "mcpServers": {
    "cc-tunnel-workspace": {
      "type": "stdio",
      "command": "/home/agent/.local/share/cc-tunnel/bin/cc-tunnel-workspace",
      "args": []
    }
  }
}
```

Codex reads MCP servers from `~/.codex/config.toml`:

```toml
[mcp_servers.cc-tunnel-workspace]
command = "/home/agent/.local/share/cc-tunnel/bin/cc-tunnel-workspace"
```

This repository is developed against Claude Code. The Codex entry follows
Codex's documented format but is not covered by its tests.

## cc-tunnel-codegraph and cc-tunnel-fast-context (optional)

Both run on the local machine against the canonical tree, so their answers
come from the code being edited, not from an index of a copy. CodeGraph needs
the project indexed locally (`codegraph init` in its root). fast-context reads
its Windsurf key from local state, so the key never reaches the remote host.

Both take an **absolute local project path**. The agent gets it from
`workspace_status`. A wrong path does not error; it quietly searches the wrong
tree. Sibling directories such as `app` and `app-fix` make that easy.

`remote-setup` records where `node`, `npx` and `codegraph` live on the local
machine. A non-interactive ssh session would not find them otherwise, and you
would get `env: node: No such file or directory`.

## MCP servers that run on the remote host

Docs (for example `@upstash/context7-mcp`) and web search need no access to the
code. Register them on the remote host in the usual way.

**Keep their API keys out of `~/.claude.json`.** `claude mcp add -e KEY=value`
stores the key in plain text in a file that tools read, back up and print
whole. A wrapper that loads the key from a separate `0600` file keeps it out:

```bash
# ~/.local/bin/exa-mcp   (chmod 700)
#!/usr/bin/env bash
set -a; . ~/.config/mcp-secrets.env; set +a     # EXA_API_KEY=...  (chmod 600)
exec npx -y exa-mcp-server
```

```bash
claude mcp add --scope user exa -- ~/.local/bin/exa-mcp
```

## Costs worth knowing

- **Tool output is paid for repeatedly.** Every result enters the context and
  is re-read on every later turn. A broad search with code snippets can be
  ~45 KB, roughly 11k tokens, re-paid each turn after it. Scoped finds and
  ranged reads are the lever.
- **The number of registered servers costs little.** Claude Code defers tool
  schemas until they are searched for. On the author's setup, over 6,883
  requests, cache reads were 94.5% of all input tokens. What costs is session
  length, not server count.
- **Restart after changing MCP configuration.** It is read when the agent
  process starts.

## Not included

Driving the local machine's signed-in browser from the remote agent is possible
over the same tunnel. Run the browser extension's MCP server locally, and
reach it the way `cc-tunnel-codegraph` does. cc-tunnel does not ship it, because
the author's version depends on a modified client.
