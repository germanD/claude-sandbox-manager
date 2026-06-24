#!/usr/bin/env bash
# SessionEnd hook for sandbox-audit.
#
# Claude Code delivers the hook payload as JSON on stdin. We extract
# transcript_path and hand it to the Python miner. This wrapper is
# deliberately fail-safe: it must NEVER fail the session, so it always
# exits 0 and swallows errors (a broken audit hook should be invisible).

set -u

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# Read the whole stdin payload (small JSON object).
payload="$(cat)"

# Extract transcript_path without assuming jq is installed: use python3,
# which we already depend on for the miner.
transcript_path="$(
  printf '%s' "$payload" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("transcript_path", ""))
except Exception:
    print("")
' 2>/dev/null
)"

if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
  python3 "$ROOT/lib/capture.py" "$transcript_path" >/dev/null 2>&1 || true
fi

exit 0
