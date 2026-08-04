#!/usr/bin/env python3
"""Cluster captured failures and suggest sandbox/permission fixes.

Usage:
    doctor.py                   # report from the scoped failures log for CWD
    doctor.py --global          # report from the global ~/.claude/sandbox-audit/failures.jsonl
    doctor.py --scan-history    # mine session transcripts for the current scope
    doctor.py --top N           # show at most N clusters (default 15)
    doctor.py --verbose         # also list which sessions/transcripts were reviewed
    doctor.py --include-archive # also read the aged-out audit trail
    doctor.py --archive         # move stale records to the audit trail now, then exit

Scope: by default reads the project-local log for the current working directory.
Use --global to read the shared log that covers all master sessions (CWD = ~
or ~/.claude).  Pre-scope records written before this feature landed remain in
the global log and are visible via --global.

Suggestions are ADVISORY only. This tool never edits settings.json. Aged-out
records are MOVED to an audit trail (failures.archive.jsonl), never deleted.
"""

import argparse
import datetime
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


def _read_last_reported():
    """Return the ISO timestamp stored in last_reported.json, or '' if absent."""
    if not os.path.exists(common.LAST_REPORTED_PATH):
        return ""
    try:
        with open(common.LAST_REPORTED_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh).get("ts", "")
    except (OSError, json.JSONDecodeError, ValueError):
        return ""


def _write_last_reported():
    """Stamp the current UTC time into last_reported.json."""
    ts = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z")
    dirn = os.path.dirname(common.LAST_REPORTED_PATH)
    if dirn:
        os.makedirs(dirn, exist_ok=True)
    with open(common.LAST_REPORTED_PATH, "w", encoding="utf-8") as fh:
        json.dump({"ts": ts}, fh)


def banner_check():
    """Print a one-liner if new failures have appeared since the last banner.

    Reads common.FAILURES_PATH and common.LAST_REPORTED_PATH; updates
    last_reported.json when a banner is printed.  All errors are swallowed so
    that a broken banner hook is invisible to the user (P1).
    Returns True if a banner was printed, False otherwise.
    """
    try:
        records = _read_jsonl(common.FAILURES_PATH)
        if not records:
            return False
        last_ts = _read_last_reported()
        new = [r for r in records if r.get("ts", "") > last_ts]
        if not new:
            return False
        n_clusters = len(cluster(new))
        print(
            f"sandbox-audit: {len(new)} new failure(s) across {n_clusters} "
            f"cluster(s) since last report — run /sandbox-audit:doctor for details"
        )
        _write_last_reported()
        return True
    except Exception:
        return False


def _read_jsonl(path):
    records = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _load_from_log(failures_path, archive_path, include_archive=False):
    records = _read_jsonl(failures_path)
    if include_archive:
        records.extend(_read_jsonl(archive_path))
    return records


def _load_from_history(cwd=None):
    """Mine transcripts in scope. Returns (records, scanned) where scanned is a
    list of {project, session, failures} for every file reviewed (project name
    redacted if denylisted, so --verbose can't leak a private path).

    cwd=None → global scope: all projects under PROJECTS_DIR.
    cwd=<path> → project scope: only the slug directory matching that path.
    """
    records = []
    scanned = []
    if cwd is None:
        pattern = os.path.join(common.PROJECTS_DIR, "*", "*.jsonl")
    else:
        slug = os.path.normpath(os.path.abspath(cwd)).replace(os.sep, "-")
        pattern = os.path.join(common.PROJECTS_DIR, slug, "*.jsonl")
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
    ap.add_argument("--banner", action="store_true",
                    help="print a one-liner if new failures exist since last "
                         "report; used by the SessionStart hook")
    ap.add_argument("--global", dest="global_scope", action="store_true",
                    help="read from the global failures log regardless of CWD")
    ap.add_argument("--scan-history", action="store_true",
                    help="mine session transcripts directly instead of the log")
    ap.add_argument("--top", type=int, default=15, help="max clusters to show")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="also list which sessions/transcripts were reviewed")
    ap.add_argument("--include-archive", action="store_true",
                    help="also read the aged-out audit trail (failures.archive.jsonl)")
    ap.add_argument("--archive", action="store_true",
                    help="move stale records (older than --retention-days) into "
                         "the audit trail now, then exit")
    ap.add_argument("--retention-days", type=int,
                    default=common.DEFAULT_RETENTION_DAYS,
                    help="age in days before a record is archived (default: %(default)s)")
    args = ap.parse_args(argv)

    if args.banner:
        banner_check()
        return 0

    # Resolve scope: --global overrides to the global log; otherwise use CWD.
    if args.global_scope:
        _data_dir, failures_path, archive_path = common.scope_paths(None)
        scope_label = "global"
        scan_cwd = None
    else:
        cwd = os.getcwd()
        _data_dir, failures_path, archive_path = common.scope_paths(cwd)
        is_global = (failures_path == common.FAILURES_PATH)
        scope_label = "global" if is_global else f"project {cwd}"
        scan_cwd = None if is_global else cwd

    if args.archive:
        moved, kept = capture.archive_stale(retention_days=args.retention_days,
                                            failures_path=failures_path,
                                            archive_path=archive_path)
        print(f"sandbox-audit: archived {moved} stale record(s) older than "
              f"{args.retention_days}d -> {archive_path}")
        print(f"active log now holds {kept} record(s) -> {failures_path}")
        return 0

    if args.scan_history:
        records, scanned = _load_from_history(cwd=scan_cwd)
        if scan_cwd is None:
            src = f"{common.PROJECTS_DIR}/*/*.jsonl"
        else:
            slug = os.path.normpath(os.path.abspath(scan_cwd)).replace(os.sep, "-")
            src = f"{common.PROJECTS_DIR}/{slug}/*.jsonl"
    else:
        records = _load_from_log(failures_path, archive_path,
                                 include_archive=args.include_archive)
        scanned = _sources_from_log(records)
        src = failures_path
        if args.include_archive:
            src += f" (+ {archive_path})"
        if not records and not os.path.exists(failures_path):
            print(f"sandbox-audit: no log at {failures_path} yet. "
                  f"Run with --scan-history to mine existing transcripts.")
            return 0
    print(f"(scope: {scope_label} | source: {src})\n")
    if args.verbose:
        print_sources(scanned)
    report(cluster(records), args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
