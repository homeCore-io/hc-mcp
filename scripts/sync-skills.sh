#!/usr/bin/env bash
# Copy homeCore's skills into the package (hc_mcp/skills), where the MCP
# server and the chat read them. Run it after the skills repo changes:
#   scripts/sync-skills.sh [path to a homeCore-io/skills checkout]
# The default is the workspace's copy, ../../skills.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
src=${1:-$here/../../skills}
[ -d "$src/skills" ] || { echo "no skills/ in $src" >&2; exit 1; }
rm -rf "$here/hc_mcp/skills"
mkdir -p "$here/hc_mcp/skills"
for d in "$src"/skills/*/; do
  [ -f "$d/SKILL.md" ] || continue
  cp -r "$d" "$here/hc_mcp/skills/"
done
rev=$(git -C "$src" rev-parse --short HEAD 2>/dev/null || echo unknown)
echo "$rev" > "$here/hc_mcp/skills/SOURCE"
echo "skills from $src ($rev): $(ls "$here/hc_mcp/skills" | grep -v SOURCE | tr '\n' ' ')"
