#!/usr/bin/env bash
# Fail if anything that identifies a real machine or person, or looks like a
# credential, is about to be published. CI runs this on every push.
#
# Read every hit. A clean exit means none of the patterns below matched - it is
# not proof that nothing private is in the tree.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  files=$(git ls-files --cached --others --exclude-standard)
else
  files=$(find . -type f -not -path './.git/*' | sed 's|^\./||')
fi
files=$(printf '%s\n' "$files" | grep -v -e '^scripts/check-publishable.sh$' -e '\.png$' -e '\.jpg$')

status=0
scan() { # label, extended regex, [allow-list regex]
  local hits allow=${3:-}
  hits=$(printf '%s\n' "$files" | tr '\n' '\0' | xargs -0 grep -nIE -- "$2" 2>/dev/null) || true
  if [[ -n "$allow" ]]; then
    hits=$(printf '%s\n' "$hits" | grep -vE -- "$allow") || true
  fi
  if [[ -n "$hits" ]]; then
    printf '\n== %s ==\n%s\n' "$1" "$hits"
    status=1
  fi
}

# Loopback, unspecified and the RFC 5737 documentation ranges are fine.
scan "IPv4 literals" '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' \
  '127\.0\.0\.1|0\.0\.0\.0|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.'
# Home directories carry a username. Placeholders are fine.
scan "home directory paths" '/(Users|home)/[A-Za-z0-9._-]+' \
  '/(Users|home)/(you|me|agent|<[^>]*>|runner|USER|\$USER)\b'
scan "private key material" '-----BEGIN [A-Z ]*PRIVATE KEY-----'
scan "public key material" '(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9-]+) AAAA[0-9A-Za-z+/]{20,}'
scan "token-shaped strings" \
  '(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|tvly-[A-Za-z0-9-]{10,}|fc-[0-9a-f]{32})'
scan "assigned secrets" \
  '(api[_-]?key|secret|token|password|passwd)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"'$<{]{12,}["'"'"']' \
  ''

if [[ "$status" -eq 0 ]]; then
  echo "check-publishable: no hits"
else
  printf '\ncheck-publishable: review the hits above before publishing\n' >&2
fi
exit "$status"
