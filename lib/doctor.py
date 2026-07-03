#!/usr/bin/env python3
"""Cluster captured failures and suggest sandbox/permission fixes.

Usage:
    doctor.py                 # report from ~/.claude/sandbox-audit/failures.jsonl
    doctor.py --scan-history  # mine ALL ~/.claude/projects/**/*.jsonl directly
    doctor.py --top N         # show at most N clusters (default 15)
    doctor.py --verbose       # also list which sessions/transcripts were reviewed

Suggestions are ADVISORY only. This MVP never edits settings.json.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capture  # noqa: E402
import common   # noqa: E402
import redact   # noqa: E402

_READONLY_CMDS = ("ls", "find", "cat", "grep", "rg", "head", "tail", "stat",
                  "pwd", "echo", "wc", "tree", "file", "which")


def _load_from_log():
    records = []
    if not os.path.exists(common.FAILURES_PATH):
        return records
    with open(common.FAILURES_PATH, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _load_from_history():
    """Mine all transcripts. Returns (records, scanned) where scanned is a list
    of {project, session, failures} describing every file reviewed (project name
    redacted if denylisted, so --verbose can't leak a private path)."""
    records = []
    scanned = []
    pattern = os.path.join(common.PROJECTS_DIR, "*", "*.jsonl")
    for path in sorted(glob.glob(pattern)):
        try:
            recs = capture.mine_transcript(path)
        except OSError:
            continue
        records.extend(recs)
        project = os.path.basename(os.path.dirname(path))
        if redact.is_denied(project):
            project = "[redacted]"
        scanned.append({
            "project": project,
            "session": os.path.basename(path),  # <session-id>.jsonl
            "failures": len(recs),
        })
    return records, scanned


def _sources_from_log(records):
    """Derive reviewed sessions from already-mined log records."""
    seen = {}
    for r in records:
        key = (r.get("project", "?"), r.get("session_id", "?"))
        seen[key] = seen.get(key, 0) + 1
    return [{"project": p, "session": s, "failures": n}
            for (p, s), n in sorted(seen.items())]


def print_sources(scanned):
    """Verbose listing of which sessions/transcripts were reviewed."""
    by_project = {}
    for s in scanned:
        by_project.setdefault(s["project"], []).append(s)
    total_files = len(scanned)
    with_failures = sum(1 for s in scanned if s["failures"])
    print(f"Sources reviewed: {total_files} session(s) across "
          f"{len(by_project)} project(s); {with_failures} with failures.\n")
    for project in sorted(by_project):
        sessions = by_project[project]
        proj_total = sum(s["failures"] for s in sessions)
        print(f"  {project}  ({len(sessions)} session(s), {proj_total} failure(s))")
        for s in sorted(sessions, key=lambda x: x["failures"], reverse=True):
            mark = "✓" if s["failures"] else "·"
            print(f"      {mark} {s['session']}  ({s['failures']})")
    print()


def cluster(records):
    clusters = {}
    for r in records:
        sig = r.get("signature", "")
        c = clusters.get(sig)
        if c is None:
            c = clusters[sig] = {
                "signature": sig,
                "kind": r.get("kind", ""),
                "tool": r.get("tool", ""),
                "count": 0,
                "sessions": set(),
                "projects": set(),
                "sample_command": r.get("command", ""),
                "sample_snippet": r.get("snippet", ""),
                "last_ts": r.get("ts", ""),
            }
        c["count"] += 1
        if r.get("session_id"):
            c["sessions"].add(r["session_id"])
        if r.get("project"):
            c["projects"].add(r["project"])
        if r.get("ts", "") > c["last_ts"]:
            c["last_ts"] = r["ts"]
        if not c["sample_command"] and r.get("command"):
            c["sample_command"] = r["command"]
    return sorted(clusters.values(), key=lambda c: c["count"], reverse=True)


def suggest(c):
    """Return a list of advisory suggestion strings for a cluster."""
    sig = c["signature"].lower()
    snippet = c["sample_snippet"].lower()
    out = []

    if "apply-seccomp" in sig or "setgroups" in sig or "apply-seccomp" in snippet:
        out.append(
            "Sandboxed Bash can't start: CC's apply-seccomp creates a nested user "
            "namespace that Ubuntu's AppArmor userns restriction blocks (Claude Code "
            "#43454). NOTE: the sandbox.seccomp.applyPath override is IGNORED by CC "
            "(#24238), so a stub workaround will not help. Verified fix on Ubuntu "
            "(needs BOTH, as root): "
            "(1) sysctl kernel.apparmor_restrict_unprivileged_userns=0 (persist in "
            "/etc/sysctl.d/); "
            "(2) unload the profile that strips caps from bwrap children — "
            "`apparmor_parser -R /etc/apparmor.d/bwrap-userns-restrict` and persist "
            "with a symlink into /etc/apparmor.d/disable/. "
            "Trade-off: re-enables unprivileged user namespaces system-wide."
        )

    if c["kind"] == "permission_denied":
        cmd = c["sample_command"].strip()
        first = cmd.split()[0] if cmd else ""
        # strip a leading path to get the bare program name
        first = os.path.basename(first)
        if first in _READONLY_CMDS:
            out.append(
                f"A read-only command (`{first}`) is being denied. The matching "
                f"deny rule is likely too broad — it blocks safe commands that "
                f"merely mention a path. Narrow the deny pattern (match the path "
                f"as a path, not as any substring), or add an allow rule for "
                f"read-only commands."
            )
        else:
            out.append(
                "Recurring permission denial. If this command is safe and you "
                "approve it repeatedly, add a scoped `allow` rule; if a deny rule "
                "is catching it unintentionally, narrow that pattern."
            )
    return out


def report(clusters, top):
    if not clusters:
        print("sandbox-audit: no failures found. 🎉")
        return
    total = sum(c["count"] for c in clusters)
    print(f"sandbox-audit — {total} failure(s) across {len(clusters)} cluster(s)\n")
    for i, c in enumerate(clusters[:top], 1):
        print(f"[{i}] ×{c['count']}  {c['kind']}  ({c['tool'] or '?'})")
        print(f"    signature: {c['signature']}")
        print(f"    projects : {', '.join(sorted(c['projects'])) or '?'}  "
              f"| sessions: {len(c['sessions'])} | last: {c['last_ts'] or '?'}")
        if c["sample_command"]:
            print(f"    command  : {c['sample_command']}")
        if c["sample_snippet"]:
            print(f"    error    : {c['sample_snippet']}")
        for s in suggest(c):
            print(f"    → fix    : {s}")
        print()
    if len(clusters) > top:
        print(f"… {len(clusters) - top} more cluster(s) hidden (use --top).")


def main(argv):
    ap = argparse.ArgumentParser(description="sandbox-audit doctor")
    ap.add_argument("--scan-history", action="store_true",
                    help="mine all session transcripts directly instead of the log")
    ap.add_argument("--top", type=int, default=15, help="max clusters to show")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="also list which sessions/transcripts were reviewed")
    args = ap.parse_args(argv)

    if args.scan_history:
        records, scanned = _load_from_history()
        src = f"{common.PROJECTS_DIR}/*/*.jsonl"
    else:
        records = _load_from_log()
        scanned = _sources_from_log(records)
        src = common.FAILURES_PATH
        if not records and not os.path.exists(common.FAILURES_PATH):
            print(f"sandbox-audit: no log at {common.FAILURES_PATH} yet. "
                  f"Run with --scan-history to mine existing transcripts.")
            return 0
    print(f"(source: {src})\n")
    if args.verbose:
        print_sources(scanned)
    report(cluster(records), args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
