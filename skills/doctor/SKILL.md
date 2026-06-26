---
name: doctor
description: Audit recurring tool failures and permission denials across Claude Code sessions and suggest sandbox/permission config fixes. Use when sandboxed Bash keeps failing, commands are unexpectedly denied, or the user asks what has been breaking across sessions.
allowed-tools: Bash, Read
---

# sandbox-audit: doctor

Surface recurring tool failures (sandbox/seccomp errors, permission denials,
command failures) and propose **advisory** config fixes. This never edits
`settings.json` — it only reports and suggests.

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

2. Run it. By default it reads the captured log
   (`~/.claude/sandbox-audit/failures.jsonl`):

   ```bash
   python3 "$DOCTOR"
   ```

3. If the log is empty or missing (e.g. first run, before any SessionEnd hook
   has fired), mine the existing transcripts directly:

   ```bash
   python3 "$DOCTOR" --scan-history
   ```

   `--scan-history` reviews **every** session transcript on disk
   (`~/.claude/projects/*/*.jsonl`) — all projects and all sessions, including
   other live ones (up to what they have flushed), not just the current session.

4. Add `--verbose` to also list exactly which sessions/transcripts were
   reviewed (with per-session failure counts; denylisted project names are
   shown as `[redacted]`):

   ```bash
   python3 "$DOCTOR" --scan-history --verbose
   ```

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
