"""Shared paths and constants for sandbox-audit."""

import os

# Fixed, predictable data dir so both the hook (capture.py) and the skill
# (doctor.py) agree on where the shared log lives, without depending on
# ${CLAUDE_PLUGIN_DATA} being exposed to skills.
DATA_DIR = os.path.expanduser("~/.claude/sandbox-audit")
FAILURES_PATH = os.path.join(DATA_DIR, "failures.jsonl")

# Where Claude Code stores per-project session transcripts.
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR
