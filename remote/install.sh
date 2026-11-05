#!/usr/bin/env bash
# Install or update the remote side of cc-tunnel, as the agent's own (non-root)
# user. Run by `cc-tunnel remote-setup` from the local machine, which stages this
# directory under ~/.local/share/cc-tunnel/stage first. Safe to run again.
#
# Needs only bash, ssh and coreutils. python3 (3.6 is enough) is used for one
# JSON merge into Claude Code's settings; without it, the hook step is skipped
# with instructions.
set -euo pipefail

: "${CC_TUNNEL_MAC_USER:?}" "${CC_TUNNEL_MAC_BIN:?}" "${CC_TUNNEL_MAC_CONFIG_DIR:?}" "${CC_TUNNEL_TUNNEL_PORT:?}"
CC_TUNNEL_MAC_PATH=${CC_TUNNEL_MAC_PATH:-/opt/homebrew/bin:/usr/local/bin}
AGENT=${CC_TUNNEL_AGENT:-claude}
STAGE="$HOME/.local/share/cc-tunnel/stage"
BIN="$HOME/.local/share/cc-tunnel/bin"
START='# >>> cc-tunnel >>>'
END='# <<< cc-tunnel <<<'

with_codegraph=0 with_fast_context=0
for arg in "$@"; do
  case "$arg" in
    --with-codegraph) with_codegraph=1 ;;
    --with-fast-context) with_fast_context=1 ;;
  esac
done

say() { printf 'remote  %s\n' "$*"; }

# Remove a managed block (if present) from a file and print the rest.
strip_block() {
  awk -v s="$START" -v e="$END" '$0==s{skip=1} !skip{print} $0==e{skip=0}' "$1"
}

# 1. Wrappers. None of them holds code or credentials: they forward stdio to
#    the local machine.
mkdir -p "$BIN"
install -m 755 "$STAGE"/remote/bin/* "$BIN"/
say "wrappers installed in $BIN"

# 2. Where things live on the local machine. Only paths: no keys, no tokens.
mkdir -p "$HOME/.config/cc-tunnel"
chmod 700 "$HOME/.config/cc-tunnel"
(
  umask 077
  {
    printf 'CC_TUNNEL_MAC_BIN=%q\n' "$CC_TUNNEL_MAC_BIN"
    printf 'CC_TUNNEL_MAC_CONFIG_DIR=%q\n' "$CC_TUNNEL_MAC_CONFIG_DIR"
    printf 'CC_TUNNEL_MAC_PATH=%q\n' "$CC_TUNNEL_MAC_PATH"
  } > "$HOME/.config/cc-tunnel/remote.env"
)
say "wrote ~/.config/cc-tunnel/remote.env"

# 3. The key this host uses to reach the local machine through the tunnel. The
#    local side authorizes it with restrict,from="127.0.0.1": it can run
#    commands, cannot forward anything, and only works through the tunnel.
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if [[ ! -f "$HOME/.ssh/cc-tunnel_mac" ]]; then
  ssh-keygen -q -t ed25519 -N '' -C "cc-tunnel@$(hostname)" -f "$HOME/.ssh/cc-tunnel_mac"
  say "generated ~/.ssh/cc-tunnel_mac"
fi

# 4. ssh config, at the TOP of the file: ssh takes the first value it finds for
#    each option, so a block appended after an existing `Host *` would be
#    silently overridden by it. HostKeyAlias keeps the known_hosts entry under a
#    stable name instead of [127.0.0.1]:port, which a second machine using the
#    same tunnel port would otherwise collide with.
config="$HOME/.ssh/config"
touch "$config"
chmod 600 "$config"
rest=$(strip_block "$config")
{
  printf '%s\n' "$START"
  cat <<EOF
Host cc-tunnel-mac
    HostName 127.0.0.1
    Port $CC_TUNNEL_TUNNEL_PORT
    User $CC_TUNNEL_MAC_USER
    HostKeyAlias cc-tunnel-mac
    IdentityFile ~/.ssh/cc-tunnel_mac
    IdentitiesOnly yes
    BatchMode yes
    StrictHostKeyChecking accept-new
    # 120 s of silence before giving up. Not lower: this connection is shared.
    ServerAliveInterval 15
    ServerAliveCountMax 8
    ControlMaster auto
    ControlPath ~/.ssh/cc-tunnel-mac-%C
    ControlPersist 10m
EOF
  printf '%s\n' "$END"
  if [[ -n "$rest" ]]; then printf '%s\n' "$rest"; fi
} > "$config.cc-tunnel-tmp"
mv "$config.cc-tunnel-tmp" "$config"
chmod 600 "$config"
say "ssh config: Host cc-tunnel-mac -> 127.0.0.1:$CC_TUNNEL_TUNNEL_PORT"

# 5. MCP registration, user scope: every project on this host gets it, and the
#    router decides per working directory which local tree it means.
is_claude=0
if [[ "$AGENT" == claude ]] && command -v claude >/dev/null 2>&1; then
  is_claude=1
fi
register() {
  claude mcp remove --scope user "$1" >/dev/null 2>&1 || true
  if claude mcp add --scope user "$1" -- "$2" >/dev/null 2>&1; then
    say "mcp: $1 registered (user scope)"
  else
    say "mcp: could not register $1 automatically - see docs/mcp.md to add it by hand"
  fi
}
if [[ "$is_claude" -eq 1 ]]; then
  register cc-tunnel-workspace "$BIN/cc-tunnel-workspace"
  if [[ "$with_codegraph" -eq 1 ]]; then register cc-tunnel-codegraph "$BIN/cc-tunnel-codegraph"; fi
  if [[ "$with_fast_context" -eq 1 ]]; then register cc-tunnel-fast-context "$BIN/cc-tunnel-fast-context"; fi
  say "restart any running agent session: MCP config is read when the process starts"
else
  say "'$AGENT' is not Claude Code (or not on PATH): register $BIN/cc-tunnel-workspace"
  say "as a stdio MCP server in that agent's config yourself - see docs/mcp.md"
fi

# 6. Claude Code extras: the memory-sync hook, the user-level rule that the
#    source is elsewhere, and the skills.
if [[ "$is_claude" -eq 1 ]]; then
  mkdir -p "$HOME/.claude/skills"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$BIN/cc-tunnel-sync-home" <<'PY'
import json, os, shutil, sys
path = os.path.expanduser("~/.claude/settings.json")
hook = sys.argv[1]
try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError:
    sys.exit("remote  settings.json is not valid JSON; add the SessionEnd hook by hand (docs/setup.md)")
entries = data.setdefault("hooks", {}).setdefault("SessionEnd", [])
if any(h.get("command") == hook for e in entries for h in e.get("hooks", [])):
    print("remote  SessionEnd hook already present")
else:
    if os.path.exists(path) and not os.path.exists(path + ".cc-tunnel-bak"):
        shutil.copy2(path, path + ".cc-tunnel-bak")
    entries.append({"hooks": [{"type": "command", "command": hook}]})
    tmp = path + ".cc-tunnel-tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    print("remote  SessionEnd hook added (memory syncs home when a session ends)")
PY
  else
    say "python3 not found: add $BIN/cc-tunnel-sync-home as a SessionEnd hook by hand (docs/setup.md)"
  fi

  rules="$HOME/.claude/CLAUDE.md"
  touch "$rules"
  rest=$(strip_block "$rules")
  {
    if [[ -n "$rest" ]]; then printf '%s\n\n' "$rest"; fi
    printf '%s\n' "$START"
    cat "$STAGE/remote/CLAUDE.md.block"
    printf '%s\n' "$END"
  } > "$rules.cc-tunnel-tmp"
  mv "$rules.cc-tunnel-tmp" "$rules"
  say "rules: cc-tunnel block in ~/.claude/CLAUDE.md"

  for dir in "$STAGE"/skills/*/; do
    name=$(basename "$dir")
    rm -rf "${HOME:?}/.claude/skills/$name"
    cp -R "$dir" "$HOME/.claude/skills/$name"
  done
  say "skills: $(ls "$STAGE/skills" | tr '\n' ' ')"
fi

# 7. Hand the public key back to the local machine, which authorizes it.
printf 'PUBKEY %s\n' "$(cat "$HOME/.ssh/cc-tunnel_mac.pub")"
