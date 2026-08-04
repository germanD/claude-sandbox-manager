---
name: doctor
description: Audit recurring tool failures and permission denials across Claude Code sessions and suggest sandbox/permission config fixes. Use when sandboxed Bash keeps failing, commands are unexpectedly denied, or the user asks what has been breaking across sessions.
allowed-tools: Bash, Read
---

# sandbox-audit: doctor

Surface recurring tool failures (sandbox/seccomp errors, permission denials,
command failures) and propose **advisory** config fixes. This never edits
`settings.json` — it only reports and suggests.

## Scope

By default `/doctor` reads the **project-local** failures log for the current
working directory (`~/.claude/sandbox-audit/projects/<slug>/failures.jsonl`).

- Sessions whose CWD is `~` or `~/.claude` are **master sessions** — they write
  to and read from the **global** log (`~/.claude/sandbox-audit/failures.jsonl`).
- All other sessions are **project sessions** — isolated to their own log.

Use `--global` to read the global log regardless of where you are invoked.
Records written before this scoping was introduced remain in the global log and
are only visible via `--global`.

## How to run

The clustering logic lives in `lib/doctor.py` inside this plugin. Locate and run it:

1. Resolve the plugin root. Prefer the `CLAUDE_PLUGIN_ROOT` env var. If it is
   empty, find the script:

   ```bash
   DOCTOR="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/lib/doctor.py}"
   if [ -z "$DOCTOR" ] || [ ! -f "$DOCTOR" ]; then
     DOCTOR="$(find "$HOME/.claude/plugins" . -name doctor.py -path '*sandbox-audit*' 2>/dev/null | head -1)"
   fi
   ```

2. Run it. By default it reads the project-scoped log for the current CWD:

   ```bash
   python3 "$DOCTOR"
   ```

3. To see failures from all master sessions (the global log):

   ```bash
   python3 "$DOCTOR" --global
   ```

4. If the log is empty or missing (e.g. first run, before any SessionEnd hook
   has fired), mine the existing transcripts directly:

   ```bash
   python3 "$DOCTOR" --scan-history          # project scope
   python3 "$DOCTOR" --global --scan-history # global scope (all projects)
   ```

   `--scan-history --global` reviews **every** session transcript on disk
   (`~/.claude/projects/*/*.jsonl`). Without `--global`, only transcripts
   whose project slug matches the current CWD are scanned.

5. Add `--verbose` to also list exactly which sessions/transcripts were
   reviewed (with per-session failure counts; denylisted project names are
   shown as `[redacted]`):

   ```bash
   python3 "$DOCTOR" --scan-history --verbose
   ```

## Audit trail (aged-out records)

The active log keeps only recent failures. Records older than the retention
window (`DEFAULT_RETENTION_DAYS`, currently 7) are **moved** — never deleted —
into an audit trail at `~/.claude/sandbox-audit/failures.archive.jsonl`. This
happens automatically on the `SessionEnd` capture path, so the default report
stays focused on what's current.

- `python3 "$DOCTOR" --include-archive` — report over the active log **and** the
  audit trail together (full history).
- `python3 "$DOCTOR" --archive` — force a rotation right now (move stale records
  to the trail), then exit. Add `--retention-days N` to override the window.

Do not delete the archive to "clean up" — it is the historical record; rolling
records off the active log is the intended way to keep reports focused.

## How to present results

- Lead with the **top recurring clusters** (highest count first): what failed,
  how many times, in which projects.
- Relay each `→ fix` suggestion, but frame it as advisory — the user decides.
- For the seccomp/`apply-seccomp` cluster, note it is a known kernel/sandbox
  issue (Claude Code #43454), not a user mistake.
- For an over-broad deny cluster (read-only commands being denied), point to the
  specific deny pattern that should be narrowed.
- If there are no failures, say so plainly.
- With `--verbose`, mention the scope reviewed (how many sessions/projects), so
  it is clear the audit spans sessions, not just the current one.

Do not propose editing settings files unless the user explicitly asks; this
skill's job is diagnosis.
