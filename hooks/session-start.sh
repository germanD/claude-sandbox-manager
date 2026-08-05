#!/usr/bin/env bash
# SessionStart hook for sandbox-audit.
#
# Runs doctor.py --banner at the beginning of each session. If new failure
# clusters have been captured since the last banner, prints a one-liner
# pointing the user to /sandbox-audit:doctor. Silent otherwise.
#
# Fail-safe: always exits 0 (P1). stdout is visible in the session preamble;
# stderr is suppressed so errors are never surfaced to the user.

set -u

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

python3 "$ROOT/lib/doctor.py" --banner 2>/dev/null || true

exit 0
