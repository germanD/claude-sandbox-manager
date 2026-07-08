#!/usr/bin/env python3
"""Mine Claude Code session transcripts for failing tool calls.

Usage:
    capture.py <transcript.jsonl> [<transcript.jsonl> ...]

For each transcript it finds tool_result content blocks with is_error == true,
joins them back to the originating tool_use to recover the tool name + input,
classifies the failure, redacts/denylists it, and appends new records to
~/.claude/sandbox-audit/failures.jsonl (deduped by session_id + tool_use_id).

Stdlib only. Designed to be called from the SessionEnd hook, and reused by
doctor.py --scan-history.
"""

import datetime
import json
import os
import re
import sys
import tempfile

# Allow running both as a module and as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import redact  # noqa: E402

# ----------------------------------------------------------------------------
# transcript parsing
# ----------------------------------------------------------------------------


def _iter_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _content_blocks(rec):
    """Return message.content as a list of blocks (or [])."""
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if isinstance(content, list):
        return content
    return []


def _block_text(block_content):
    """Flatten a tool_result's content (string | list of blocks) to text."""
    if isinstance(block_content, str):
        return block_content
    if isinstance(block_content, list):
        parts = []
        for b in block_content:
            if isinstance(b, dict):
                parts.append(b.get("text") or b.get("content") or "")
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(p for p in parts if p)
    return ""


def _input_summary(tool, tool_input):
    """Human-meaningful one-liner describing what the tool was asked to do."""
    if not isinstance(tool_input, dict):
        return ""
    if tool == "Bash":
        return tool_input.get("command", "") or ""
    for key in ("file_path", "path", "pattern", "url", "notebook_path"):
        if key in tool_input:
            return str(tool_input[key])
    try:
        return json.dumps(tool_input)[:200]
    except (TypeError, ValueError):
        return ""


# ----------------------------------------------------------------------------
# classification + signatures
# ----------------------------------------------------------------------------

# Specific markers for Claude Code's permission gate. We deliberately do NOT
# match a bare "permission denied" — a runtime stderr (e.g. the seccomp error
# "apply-seccomp: ... Permission denied") says that too but is a runtime failure.
_PERM_MARKERS = (
    "doesn't want to proceed with this tool use",
    "requested permissions to use",
)


# Error texts that are not real failures: collateral cancellations when a
# sibling tool in the same parallel batch errored, and user interruptions.
# These are noise — they inflate counts and bury actual problems.
_NOISE_MARKERS = (
    "cancelled: parallel tool call",
    "[request interrupted by user",
)


def is_noise(error_text):
    low = error_text.lower()
    return any(m in low for m in _NOISE_MARKERS)


def classify(error_text):
    low = error_text.lower()
    if any(m in low for m in _PERM_MARKERS):
        return "permission_denied"
    # Deny-rule / permission-system message, e.g.
    # "Permission to use Bash with command ... has been denied".
    if "permission to use" in low and "has been denied" in low:
        return "permission_denied"
    return "runtime_failure"


def _salient_line(error_text):
    """Pick the most informative line of an error message."""
    for raw in error_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"exit code \d+", line.lower()):
            continue
        return line
    return error_text.strip()


def _canon(text):
    """Canonicalize variable bits so equivalent failures cluster together."""
    t = text
    t = re.sub(r"0x[0-9a-fA-F]+", "0xN", t)
    t = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
              r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "<uuid>", t)
    t = re.sub(r"\b\d+\b", "N", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def signature(kind, tool, command, error_text):
    if kind == "permission_denied":
        return f"permission_denied:{tool}:{_canon(command)[:80]}"
    return f"{tool}:{_canon(_salient_line(error_text))[:140]}"


# ----------------------------------------------------------------------------
# mining
# ----------------------------------------------------------------------------


def mine_transcript(path):
    """Return a list of failure records mined from one transcript file.

    Records are already redacted; denylisted records are masked (sensitive
    fields replaced with redacted placeholders), not dropped.
    """
    project = os.path.basename(os.path.dirname(os.path.abspath(path)))
    tool_uses = {}     # tool_use_id -> (tool_name, input_summary)
    records = []
    last_session = ""
    last_cwd = ""

    for rec in _iter_lines(path):
        if rec.get("sessionId"):
            last_session = rec["sessionId"]
        if rec.get("cwd"):
            last_cwd = rec["cwd"]
        ts = rec.get("timestamp", "")

        for block in _content_blocks(rec):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                tid = block.get("id")
                if tid:
                    tool = block.get("name", "")
                    tool_uses[tid] = (tool, _input_summary(tool, block.get("input")))
            elif btype == "tool_result" and block.get("is_error") is True:
                tid = block.get("tool_use_id", "")
                tool, command = tool_uses.get(tid, ("", ""))
                error_text = _block_text(block.get("content"))

                if is_noise(error_text):
                    continue

                # Pull richer Bash detail from toolUseResult when it's an object.
                tur = rec.get("toolUseResult")
                if isinstance(tur, dict):
                    stderr = tur.get("stderr") or ""
                    if stderr and stderr not in error_text:
                        error_text = (error_text + "\n" + stderr).strip()

                kind = classify(error_text)

                # Privacy gate: if the record touches a denylisted path, MASK the
                # sensitive parts rather than dropping it — we keep the learnable
                # shape (e.g. "a read-only command was denied") without persisting
                # the private path/command/output.
                if redact.is_denied(command, last_cwd, error_text, project):
                    command_out = redact.mask_command(tool, command)
                    snippet_out = redact.mask_snippet(kind)
                    cwd_out = "[redacted]"
                    project_out = "[redacted]"
                else:
                    command_out = redact.clean_snippet(command, limit=200)
                    snippet_out = redact.clean_snippet(error_text, limit=300)
                    cwd_out = last_cwd
                    project_out = project

                records.append({
                    "ts": ts,
                    "session_id": last_session,
                    "tool_use_id": tid,
                    "project": project_out,
                    "cwd": cwd_out,
                    "tool": tool,
                    "kind": kind,
                    # Signature is built from the SAFE (masked/cleaned) values so
                    # it never leaks and still clusters equivalent failures.
                    "signature": signature(kind, tool, command_out, snippet_out),
                    "command": command_out,
                    "snippet": snippet_out,
                })

    return records


# ----------------------------------------------------------------------------
# persistence
# ----------------------------------------------------------------------------


def _existing_keys(*paths):
    """Dedup keys (session_id, tool_use_id) seen across the given log files."""
    keys = set()
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        for rec in _iter_lines(path):
            keys.add((rec.get("session_id", ""), rec.get("tool_use_id", "")))
    return keys


def append_records(records):
    """Append new (deduped) records to the shared failures log. Returns count.

    Dedup spans BOTH the active log and the audit trail (invariant: archiving a
    record must not let a later scan resurrect it into the active log).
    """
    common.ensure_data_dir()
    seen = _existing_keys(common.FAILURES_PATH, common.ARCHIVE_PATH)
    new = 0
    with open(common.FAILURES_PATH, "a", encoding="utf-8") as fh:
        for r in records:
            key = (r["session_id"], r["tool_use_id"])
            if key in seen:
                continue
            seen.add(key)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            new += 1
    return new


def _parse_ts(ts):
    """Parse an ISO-8601 record timestamp (with trailing 'Z') to an aware
    datetime, or None if it is missing/unparseable. Python 3.9 compatible."""
    if not ts or not isinstance(ts, str):
        return None
    t = ts.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _rewrite_jsonl(path, records):
    """Atomically replace a jsonl file with exactly `records` (temp file + os.replace)."""
    common.ensure_data_dir()
    dirn = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=dirn, prefix=".tmp-audit-", suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def archive_stale(retention_days=None, now=None):
    """Move records older than the retention window out of the active log and
    into the audit trail. Records are MOVED, never deleted. Returns
    (archived_count, kept_count).

    Records with a missing/unparseable timestamp are conservatively KEPT active
    (we never archive something we can't date). The append to the archive is
    deduped, and the active log is rewritten atomically, so this is safe to run
    repeatedly (idempotent) and from the fail-safe hook path.
    """
    if retention_days is None:
        retention_days = common.DEFAULT_RETENTION_DAYS
    active_path = common.FAILURES_PATH
    if not os.path.exists(active_path):
        return (0, 0)
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=retention_days)

    keep = []
    stale = []
    for rec in _iter_lines(active_path):
        ts = _parse_ts(rec.get("ts", ""))
        if ts is not None and ts < cutoff:
            stale.append(rec)
        else:
            keep.append(rec)

    if not stale:
        return (0, len(keep))

    # Append the aged-out records to the trail (deduped), THEN drop them from
    # the active log. Order matters: if the rewrite fails, nothing is lost —
    # the records are already safe in the archive and dedup prevents doubling.
    common.ensure_data_dir()
    seen = _existing_keys(common.ARCHIVE_PATH)
    with open(common.ARCHIVE_PATH, "a", encoding="utf-8") as fh:
        for r in stale:
            key = (r.get("session_id", ""), r.get("tool_use_id", ""))
            if key in seen:
                continue
            seen.add(key)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    _rewrite_jsonl(active_path, keep)
    return (len(stale), len(keep))


def main(argv):
    if not argv:
        print("usage: capture.py <transcript.jsonl> [...]", file=sys.stderr)
        return 2
    all_records = []
    for path in argv:
        if os.path.isfile(path):
            try:
                all_records.extend(mine_transcript(path))
            except OSError:
                continue
    added = append_records(all_records)
    # Rolling maintenance: age stale records out to the audit trail so the
    # active log stays focused. Fail-safe — this must never break the capture
    # or SessionEnd-hook path, so any error here is swallowed.
    moved = 0
    try:
        moved, _kept = archive_stale()
    except Exception:
        moved = 0
    msg = (f"sandbox-audit: mined {len(all_records)} failure(s), "
           f"{added} new -> {common.FAILURES_PATH}")
    if moved:
        msg += f"; archived {moved} stale -> {common.ARCHIVE_PATH}"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
