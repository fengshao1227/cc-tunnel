---
name: cc-tunnel-workspace
description: Use whenever the cc-tunnel-workspace MCP tools (workspace_read, workspace_find, workspace_patch, workspace_exec, ...) are available and you need to read, search, edit, build, test or run git on project source. The source is on the user's local machine, not on the host you are running on; these tools are the only way to reach it. Also covers cc-tunnel-codegraph and cc-tunnel-fast-context.
---

# Working on a cc-tunnel workspace

You are running on a remote host. The project's source is on the user's local
machine, and every `workspace_*` call runs there, over a reverse SSH tunnel,
against the one real tree. The directory you are in holds only rules and
memory. There is no copy of the code here, so nothing here can go stale. But
nothing here is the code either.

## The rule that matters most

Never use the built-in Read / Grep / Glob / Edit / Write tools, or a shell on
this host, for project source. They will find an empty stub, or a leftover
copy, and their answers will look right and be wrong. Use `workspace_*` for
everything that touches the code.

## Start of every task

1. `workspace_status`: the local absolute root, git branch and status of each
   repository in it, and who (if anyone) holds the write lock.
2. Keep that absolute root. `cc-tunnel-codegraph` and `cc-tunnel-fast-context`
   take it as their project path. A wrong path does not error; it searches the
   wrong tree (a sibling such as `app` versus `app-fix` is the usual trap).

## Reading

- Locate first: `workspace_find` with a `pattern`, scoped by `path`, `glob` or
  `type`. `output_mode: "files"` lists matching files; `files_only: true`
  matches file *names* by glob.
- Then read only the range you need: `workspace_read` with
  `start_line`/`end_line`. Without a range you get the first 600 lines.
- Every result enters your context and is re-read on every later turn. Small
  scoped reads are cheaper than one big one.

## Editing

- Prefer `workspace_patch`: `old_text` must match exactly once, so include a
  line or two of context. It applies to the file's current bytes, so another
  agent's change elsewhere in the same file survives.
- To overwrite a whole existing file, use `workspace_write` with
  `expected_sha256` set to the hash prefix from your last `workspace_read`. It
  refuses if the file changed since. Without it, you overwrite blindly.
- Before a multi-file change that must not interleave with another agent's:
  `workspace_lock` with a `reason`, make the edits, then `workspace_unlock`.
  While you hold it, other sessions' writes are refused. It is released
  automatically if your session dies.
- Sensitive files (`.env*`, credential files, private keys) are refused by the
  file tools and excluded from search. Do not route around that with
  `workspace_exec`; ask the user instead.

## Running commands

- `workspace_exec` runs on the local machine: builds, tests, git, docker. It
  runs in the workspace root, or in `cwd`.
- Calls run one at a time. Anything over a minute should use
  `background: true`, then `workspace_job` with `id` and `wait_seconds` (up to
  600): one call instead of a polling loop.
- **A timeout is not a failure.** The command may have finished its side
  effect after the reply was lost. Before re-running anything that changes
  state, such as `git push`, a migration or a deploy, check whether it already
  happened.
- Keep output small: filter with `grep`, `head` and `tail` rather than raising
  `max_output_chars`.

## Git

- Before trusting "up to date", `git fetch`. An https remote cannot prompt for
  credentials in this non-interactive session. Its fetch fails, `origin/*`
  stays at an old value, and `git rev-list --count HEAD..origin/main` then says
  `0` for a checkout that is far behind. Check `git remote -v`; ssh remotes
  work.
- The user may also have local agents editing this tree. Look at
  `workspace_status` before committing, and do not commit files you did not
  change.

## When the tools fail

If the `workspace_*` tools are missing, time out, or fail to connect, say so
plainly and follow the `cc-tunnel-doctor` skill. Do not fall back to whatever
happens to be on this host.
