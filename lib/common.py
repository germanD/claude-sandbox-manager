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

# Timestamp written by the SessionStart banner after it fires; used to
# suppress repeated banners for the same failure clusters.
LAST_REPORTED_PATH = os.path.join(DATA_DIR, "last_reported.json")

# Default age (in days) before a record rolls off the active log into the
# audit trail. The capture/hook path applies this automatically.
DEFAULT_RETENTION_DAYS = 7

# Where Claude Code stores per-project session transcripts.
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


def _slug(cwd_abs: str) -> str:
    """Convert an absolute path to the slug CC uses for ~/.claude/projects/<slug>.

    The leading hyphen for absolute paths (e.g. /home/user/repo → -home-user-repo)
    is intentional — it matches exactly how Claude Code itself names those dirs.
    """
    return cwd_abs.replace(os.sep, "-")


def ensure_data_dir(data_dir=None):
    target = data_dir if data_dir is not None else DATA_DIR
    os.makedirs(target, exist_ok=True)
    return target


def scope_paths(cwd=None):
    """Return (data_dir, failures_path, archive_path) scoped to cwd.

    Master sessions (cwd is $HOME or $HOME/.claude) and absent/empty CWD use
    the global data dir.  All other CWDs get a per-project sub-directory whose
    name is the normalised absolute path with each '/' replaced by '-' — the
    same slug convention Claude Code uses for ~/.claude/projects/<slug>/.

    This is the single source of truth for all path decisions (P6, P8).
    """
    home = os.path.expanduser("~")
    claude_home = os.path.join(home, ".claude")

    if cwd:
        cwd_abs = os.path.normpath(os.path.abspath(os.path.expanduser(str(cwd))))
        master_dirs = {os.path.normpath(home), os.path.normpath(claude_home)}
        if cwd_abs not in master_dirs:
            slug = _slug(cwd_abs)
            data_dir = os.path.join(DATA_DIR, "projects", slug)
            return (
                data_dir,
                os.path.join(data_dir, "failures.jsonl"),
                os.path.join(data_dir, "failures.archive.jsonl"),
            )

    return (DATA_DIR, FAILURES_PATH, ARCHIVE_PATH)
