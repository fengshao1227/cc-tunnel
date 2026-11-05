#!/usr/bin/env bash
# Install cc-tunnel on the local machine (the one that keeps the code).
# Safe to run again: it updates the tools and never overwrites your config.
#
#   ./install.sh                 install into ~/.local
#   PREFIX=/opt/cc-tunnel ./install.sh
#   ./install.sh --uninstall     remove the tools, launchd job and skills (keeps your config)
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
PREFIX=${PREFIX:-$HOME/.local}
BIN="$PREFIX/bin"
SHARE="$PREFIX/share/cc-tunnel"
CONFIG_DIR=${CC_TUNNEL_CONFIG_DIR:-$HOME/.config/cc-tunnel}
LABEL=${CC_TUNNEL_LAUNCHD_LABEL:-dev.cc-tunnel}
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/cc-tunnel"
TOOLS=(cc-tunnel cc-tunnel-mcp cc-tunnel-router cc-tunnel-link cc-tunnel-session cc-tunnel-memory-merge)
LOCAL_SKILLS=(cc-tunnel-doctor cc-tunnel-handoff)

say() { printf '%s\n' "$*"; }

if [[ "${1:-}" == --uninstall ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  for tool in "${TOOLS[@]}"; do rm -f "${BIN:?}/$tool"; done
  rm -rf "${SHARE:?}"
  for skill in "${LOCAL_SKILLS[@]}"; do rm -rf "${HOME:?}/.claude/skills/$skill"; done
  say "removed cc-tunnel from $BIN, $SHARE and ~/.claude/skills; kept $CONFIG_DIR"
  say "the remote side is untouched; see docs/setup.md to remove it there"
  exit 0
fi

missing=()
for tool in python3 ssh rsync; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  say "missing: ${missing[*]}"
  exit 1
fi
command -v rg >/dev/null 2>&1 \
  || say "warning: ripgrep (rg) not found - workspace_find needs it (brew install ripgrep)"
# A non-interactive ssh session finds /usr/bin/python3 first, whatever an
# interactive shell would pick, and the workspace server runs under it.
if [[ "$(uname)" == Darwin ]] && ! /usr/bin/python3 --version >/dev/null 2>&1; then
  say "warning: /usr/bin/python3 is missing - install the command line tools: xcode-select --install"
fi

mkdir -p "$BIN" "$SHARE"
for tool in "${TOOLS[@]}"; do
  install -m 755 "$REPO/local/bin/$tool" "$BIN/$tool"
done
rm -rf "${SHARE:?}/remote" "${SHARE:?}/skills"
cp -R "$REPO/remote" "$REPO/skills" "$SHARE/"
say "installed ${TOOLS[*]}"
say "  -> $BIN"

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/config" ]]; then
  install -m 600 "$REPO/config/config.example" "$CONFIG_DIR/config"
  say "created $CONFIG_DIR/config - edit it before going further"
fi
if [[ ! -f "$CONFIG_DIR/projects.conf" ]]; then
  install -m 600 "$REPO/config/projects.conf.example" "$CONFIG_DIR/projects.conf"
fi

if [[ "$(uname)" == Darwin ]]; then
  mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"
  sed -e "s|@LABEL@|$LABEL|g" -e "s|@BIN@|$BIN|g" -e "s|@LOG_DIR@|$LOG_DIR|g" \
    "$REPO/local/launchd/dev.cc-tunnel.plist.template" > "$PLIST"
  say "launchd job written: $PLIST (not started - run: cc-tunnel tunnel start)"
else
  say "not macOS: run $BIN/cc-tunnel-link under your own supervisor (e.g. a systemd user unit)"
fi

# The doctor and handoff skills are for agents on this machine too.
if [[ -d "$HOME/.claude" ]]; then
  mkdir -p "$HOME/.claude/skills"
  for skill in "${LOCAL_SKILLS[@]}"; do
    rm -rf "${HOME:?}/.claude/skills/$skill"
    cp -R "$REPO/skills/$skill" "$HOME/.claude/skills/$skill"
  done
  say "skills ${LOCAL_SKILLS[*]} -> ~/.claude/skills"
fi

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) say "add $BIN to your PATH" ;;
esac

cat <<NEXT

next (docs/setup.md has the details):
  1. edit $CONFIG_DIR/config
  2. once, as root on the remote host: scripts/vps-bootstrap.sh
  3. cc-tunnel tunnel start && cc-tunnel remote-setup
  4. in a project root: cc-tunnel map && cc-tunnel check && cc-tunnel
NEXT
