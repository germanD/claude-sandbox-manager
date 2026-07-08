"""Shared paths and constants for sandbox-audit."""

import os

# Fixed, predictable data dir so both the hook (capture.py) and the skill
# (doctor.py) agree on where the shared log lives, without depending on
# ${CLAUDE_PLUGIN_DATA} being exposed to skills.
DATA_DIR = os.path.expanduser("~/.claude/sandbox-audit")
FAILURES_PATH = os.path.join(DATA_DIR, "failures.jsonl")

# Audit trail: records that have aged out of the active log are MOVED here
# (never deleted) so the active log stays focused on what's current while the
# full history is still recoverable. See capture.archive_stale.
ARCHIVE_PATH = os.path.join(DATA_DIR, "failures.archive.jsonl")

# Default age (in days) before a record rolls off the active log into the
# audit trail. The capture/hook path applies this automatically.
DEFAULT_RETENTION_DAYS = 7

# Where Claude Code stores per-project session transcripts.
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR
