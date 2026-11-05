#!/usr/bin/env bash
# One-time setup on the remote host, as root: the agent's account and a
# forward-only account for the reverse tunnel. Safe to run again.
#
#   sudo bash vps-bootstrap.sh --agent-key cc-tunnel_remote.pub --tunnel-key cc-tunnel_tunnel.pub
#
#   --agent-user NAME    the agent's login (default: agent)
#   --tunnel-user NAME   the tunnel's login (default: cc-tunnel-link)
#   --tunnel-port PORT   loopback port the tunnel listens on (default: 22022)
#
# The agent account is an ordinary user with no sudo. The tunnel account cannot
# run commands or open a shell; on OpenSSH 7.8+ its key may only listen on
# 127.0.0.1:<tunnel port> and nothing else.
set -euo pipefail

AGENT_USER=agent
TUNNEL_USER=cc-tunnel-link
TUNNEL_PORT=22022
AGENT_KEY=''
TUNNEL_KEY=''

usage() { sed -n '2,15p' "$0" >&2; exit 2; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-key) AGENT_KEY=${2:-}; shift 2 ;;
    --tunnel-key) TUNNEL_KEY=${2:-}; shift 2 ;;
    --agent-user) AGENT_USER=${2:-}; shift 2 ;;
    --tunnel-user) TUNNEL_USER=${2:-}; shift 2 ;;
    --tunnel-port) TUNNEL_PORT=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done
[[ "$(id -u)" -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ -r "$AGENT_KEY" && -r "$TUNNEL_KEY" ]] || usage
[[ "$TUNNEL_PORT" =~ ^[0-9]+$ ]] || usage

say() { printf 'bootstrap  %s\n' "$*"; }

add_key() { # user, authorized_keys line
  local user=$1 line=$2 home material
  home=$(getent passwd "$user" | cut -d: -f6)
  install -d -m 700 -o "$user" -g "$(id -gn "$user")" "$home/.ssh"
  touch "$home/.ssh/authorized_keys"
  material=$(awk '{for (i=1;i<=NF;i++) if ($i ~ /^AAAA/) {print $i; exit}}' <<< "$line")
  if grep -qF "$material" "$home/.ssh/authorized_keys"; then
    say "$user: key already authorized"
  else
    printf '%s\n' "$line" >> "$home/.ssh/authorized_keys"
    say "$user: key authorized"
  fi
  chown "$user:$(id -gn "$user")" "$home/.ssh/authorized_keys"
  chmod 600 "$home/.ssh/authorized_keys"
}

# The agent: a normal account with a home for its stubs, memory and sessions.
if ! id "$AGENT_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$AGENT_USER"
  say "created user $AGENT_USER"
fi
agent_home=$(getent passwd "$AGENT_USER" | cut -d: -f6)
install -d -m 755 -o "$AGENT_USER" -g "$(id -gn "$AGENT_USER")" "$agent_home/projects"
add_key "$AGENT_USER" "$(cat "$AGENT_KEY")"

# The tunnel: no shell, no commands, port forwarding only.
nologin=$(command -v nologin || echo /sbin/nologin)
if ! id "$TUNNEL_USER" >/dev/null 2>&1; then
  useradd -m -s "$nologin" "$TUNNEL_USER"
  say "created user $TUNNEL_USER (shell: $nologin)"
fi
options='restrict,port-forwarding,command="/bin/false"'
version=$(ssh -V 2>&1 | sed -n 's/^OpenSSH_\([0-9]*\)\.\([0-9]*\).*/\1 \2/p')
read -r major minor <<< "${version:-0 0}"
if [[ "$major" -gt 7 || ( "$major" -eq 7 && "$minor" -ge 8 ) ]]; then
  options+=",permitlisten=\"127.0.0.1:$TUNNEL_PORT\""
else
  say "OpenSSH ${major}.${minor} is older than 7.8: the tunnel key can open any remote forward,"
  say "not only 127.0.0.1:$TUNNEL_PORT. Upgrade OpenSSH to pin it to that one port."
fi
add_key "$TUNNEL_USER" "$options $(cat "$TUNNEL_KEY")"

# Remote forwards must stay on loopback, or anyone who can reach this host
# could connect to the local machine's sshd through the tunnel.
if grep -qEi '^[[:space:]]*GatewayPorts[[:space:]]+(yes|clientspecified)' /etc/ssh/sshd_config 2>/dev/null; then
  say "WARNING: sshd_config sets GatewayPorts - the tunnel port could be reachable from outside."
fi
if grep -qEi '^[[:space:]]*AllowTcpForwarding[[:space:]]+(no|local)' /etc/ssh/sshd_config 2>/dev/null; then
  say "WARNING: sshd_config disables remote forwarding - allow it for $TUNNEL_USER, or the tunnel cannot start."
fi

say "done. Install the agent (e.g. Claude Code) as $AGENT_USER, then from the local machine:"
say "  cc-tunnel tunnel start && cc-tunnel remote-setup"
