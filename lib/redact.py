"""Redaction and denylisting for sandbox-audit.

Hard requirement: nothing is persisted to failures.jsonl until it has passed
through here. Two layers:

  1. is_denied() -- if text touches a denylisted path/command (e.g. priv-misc),
                    the caller (capture.py) MASKS the record's sensitive fields
                    rather than persisting the raw values, keeping only the
                    learnable shape. Privacy beats completeness.
  2. redact()    -- scrub secret-shaped substrings (tokens, keys, auth headers)
                    from text that IS kept.

Stdlib only. The denylist is seeded from lib/denylist.txt (one pattern per
line, '#' comments allowed) plus a few built-in defaults.
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_DENYLIST_FILE = os.path.join(_HERE, "denylist.txt")

# Substrings that, if present anywhere in a record's searchable text, cause the
# record's sensitive fields to be masked. Always-on defaults; extended by
# denylist.txt.
_DEFAULT_DENY = ["priv-misc"]


def load_denylist():
    """Return the list of denylist substrings (lowercased)."""
    patterns = list(_DEFAULT_DENY)
    try:
        with open(_DENYLIST_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    except FileNotFoundError:
        pass
    # de-dupe, lowercase for case-insensitive matching
    return sorted({p.lower() for p in patterns})


_DENY = load_denylist()


def is_denied(*texts):
    """True if any provided text contains a denylisted substring."""
    hay = " ".join(t for t in texts if t).lower()
    return any(pat in hay for pat in _DENY)


# Masking, not dropping: when a record touches a denylisted path we still want
# the *shape* of the failure (e.g. "a read-only command was denied") for
# learning, but must not persist the private path/command itself.

def mask_command(tool, command):
    """Return a privacy-safe stand-in for a denylisted command/input.

    For Bash we keep only the program name (the learnable bit — e.g. is this a
    read-only `ls`?) and mask the arguments. For other tools we mask entirely,
    since their "command" is typically a file path.
    """
    if tool == "Bash" and command:
        toks = command.strip().split()
        prog = os.path.basename(toks[0]) if toks else ""
        if not prog or is_denied(prog):
            return "[denied]"
        return f"{prog} [denied-args]" if len(toks) > 1 else prog
    return "[denied-path]"


def mask_snippet(kind):
    """Generic, leak-free snippet for a denylisted record."""
    if kind == "permission_denied":
        return "[permission denied — details redacted by denylist]"
    return "[error — details redacted by denylist]"


# Secret-shaped patterns. Conservative: aimed at obvious credentials, not at
# scrubbing every possible PII. (pattern, replacement)
_SECRET_PATTERNS = [
    # PEM private keys / blocks
    (re.compile(r"-----BEGIN[^-]*?PRIVATE KEY-----.*?-----END[^-]*?PRIVATE KEY-----", re.DOTALL),
     "[REDACTED_PRIVATE_KEY]"),
    # Authorization / Bearer headers
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*)(bearer\s+)?[A-Za-z0-9._\-+/=]{8,}"),
     r"\1[REDACTED]"),
    # GitHub / GitLab style tokens
    (re.compile(r"\b(ghp|gho|ghu|ghs|ghr|github_pat|glpat)[-_][A-Za-z0-9_]{8,}\b"),
     "[REDACTED_TOKEN]"),
    # AWS access key ids
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    # Anthropic-style keys
    (re.compile(r"\bsk-[A-Za-z0-9\-]{16,}\b"), "[REDACTED_API_KEY]"),
    # KEY=value / TOKEN=value / SECRET=value / PASSWORD=value env assignments
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY)[A-Z0-9_]*\s*[:=]\s*)('|\")?[^\s'\"]{4,}\2?"),
     r"\1[REDACTED]"),
]


def redact(text):
    """Scrub secret-shaped substrings from text. Returns redacted text."""
    if not text:
        return text
    out = text
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def clean_snippet(text, limit=300):
    """Redact then truncate a snippet for storage."""
    if not text:
        return ""
    red = redact(text)
    red = red.strip()
    if len(red) > limit:
        red = red[:limit] + "…"
    return red
