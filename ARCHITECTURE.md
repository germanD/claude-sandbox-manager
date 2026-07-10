# ARCHITECTURE.md — sandbox-audit: as-built reference

This document describes the current implementation (v0.1.x, Phase-1 MVP).
For the original design notes and motivation see `ONBOARDING.md`.
For agent/contributor guidance see `AGENTS.md`.

---

## Overview

sandbox-audit is a Claude Code plugin that mines session transcripts for failing
tool calls and permission denials, clusters recurring patterns, and suggests
config fixes. It ships as a single plugin: a `SessionEnd` hook, a Python library,
and a `/sandbox-audit:doctor` skill.

Nothing leaves the machine. Suggestions are advisory; no config is auto-applied.

---

## Data Flow

```
SessionEnd hook
  └─▶ hooks/session-end.sh          (fail-safe bash wrapper, always exits 0)
        └─▶ lib/capture.py <transcript_path>
              ├─ parse transcript JSONL (tool_use + tool_result blocks)
              ├─ classify: permission_denied | runtime_failure
              ├─ filter noise (cancelled parallels, user interruptions)
              ├─ privacy gate: lib/redact.py
              │     ├─ denylist masking (mask sensitive fields, keep shape)
              │     └─ secret scrubbing (tokens, keys, auth headers)
              ├─ dedup by (session_id, tool_use_id) across active + archive
              ├─ append to ~/.claude/sandbox-audit/failures.jsonl
              └─ archive_stale() → ~/.claude/sandbox-audit/failures.archive.jsonl

/sandbox-audit:doctor skill
  └─▶ lib/doctor.py
        ├─ load from failures.jsonl  (or --scan-history: mine transcripts directly)
        ├─ cluster records by signature field
        ├─ suggest() per cluster (advisory only — never edits settings.json)
        └─ print ranked report
```

---

## Components

### `lib/common.py` — Shared constants

Single source of truth for paths. Both the hook and the skill import from here so
they always agree. Never hardcode a path elsewhere.

| Constant | Value |
|---|---|
| `DATA_DIR` | `~/.claude/sandbox-audit/` |
| `FAILURES_PATH` | `~/.claude/sandbox-audit/failures.jsonl` |
| `ARCHIVE_PATH` | `~/.claude/sandbox-audit/failures.archive.jsonl` |
| `PROJECTS_DIR` | `~/.claude/projects/` |
| `DEFAULT_RETENTION_DAYS` | `7` |

---

### `lib/redact.py` — Privacy gate

Two-layer guard. Every record passes through before being written to disk.

**Layer 1 — Denylist** (`is_denied()`)

If the command, path, cwd, error text, or project name contains a denylisted
substring (default: `priv-misc`; extended by `lib/denylist.txt`), the record's
sensitive fields are **masked**, not dropped:

- `mask_command(tool, cmd)` — for Bash, keeps only the program name (the learnable
  bit: was this a read-only `ls`?); for other tools returns `[denied-path]`.
- `mask_snippet(kind)` — returns a generic placeholder.
- `project` and `cwd` are replaced with `[redacted]`.

The failure *shape* (tool, kind, masked command) is preserved for clustering.
Private content is never written.

**Layer 2 — Secret scrubbing** (`redact()`)

Applied to text that IS kept. Patterns:
- PEM private key blocks
- `Authorization: Bearer <token>` headers
- GitHub/GitLab tokens (`ghp_`, `glpat-`, etc.)
- AWS access key IDs (`AKIA…`)
- Anthropic API keys (`sk-…`)
- `*_TOKEN=`, `*_SECRET=`, `*_PASSWORD=`, `*_API_KEY=` env assignments

`clean_snippet(text, limit)` calls `redact()` then truncates to `limit` chars.

---

### `lib/capture.py` — Transcript miner

Called by the hook with the transcript path at session end. Also importable by
`doctor.py` for `--scan-history`.

**Parsing**

Iterates transcript lines, builds a `tool_use_id → (tool_name, input_summary)`
map from `tool_use` blocks, then finds `tool_result` blocks with `is_error: true`
and joins them. Enriches error text with `toolUseResult.stderr` when it appears
as a sibling key (Bash extended results).

**Classification** (`classify(error_text)`)

| Result | Trigger |
|---|---|
| `permission_denied` | `"doesn't want to proceed with this tool use"` |
| `permission_denied` | `"requested permissions to use"` |
| `permission_denied` | `"permission to use … has been denied"` |
| `runtime_failure` | everything else, including bare `"permission denied"` (e.g. seccomp) |

The seccomp stderr (`apply-seccomp: … Permission denied`) is a *runtime* failure,
not a CC permission gate. A regression test (`TestClassify`) guards this boundary.

**Noise filtering** (`is_noise(error_text)`)

Drops before classification:
- `"cancelled: parallel tool call"` — collateral when a sibling tool errored
- `"[request interrupted by user"` — user interruption

**Signature** (canonical fingerprint for clustering)

- `permission_denied`: `permission_denied:<tool>:<canon(command[:80])>`
- `runtime_failure`: `<tool>:<canon(salient_error_line[:140])>`

Canonicalization (`_canon`) strips hex addresses (`0xN`), UUIDs (`<uuid>`), and
integers (`N`), and collapses whitespace. Built from the **safe (masked/cleaned)**
values — never from raw inputs — so it clusters without ever leaking.

**Persistence**

- `append_records(records)`: deduplicates by `(session_id, tool_use_id)` against
  both `failures.jsonl` AND `failures.archive.jsonl`, then appends new records
  atomically. Idempotent: re-running the hook or `--scan-history` never double-counts.
- `archive_stale(retention_days, now)`: moves records older than the retention window
  from the active log to the archive. Appends to the archive first, then rewrites
  the active log atomically via a temp file + `os.replace()`. A crash between the
  two steps is safe — records are in the archive and dedup prevents re-ingestion.
  Records with a missing or unparseable `ts` are never archived (can't date them).

**`main(argv)`** orchestrates: mine all provided transcripts → `append_records` →
`archive_stale` (swallowed; must never break the hook path).

---

### `lib/doctor.py` — Cluster and suggest

Reads the active log (or mines transcripts directly via `--scan-history`),
groups records by `signature`, and prints a ranked report.

**Loading**

- Default: `_load_from_log()` reads `failures.jsonl` (+ archive if `--include-archive`).
- `--scan-history`: `_load_from_history()` globs `~/.claude/projects/*/*.jsonl` and
  calls `capture.mine_transcript()` on each. Denylisted project names appear as
  `[redacted]` even in the `--verbose` sources listing.

**Clustering** (`cluster(records)`)

Groups by `signature`. Each cluster tracks: count, sessions (set), projects (set),
last timestamp, a sample command, and a sample error snippet.

**Suggestions** (`suggest(cluster)`)

| Condition | Advisory |
|---|---|
| `apply-seccomp` or `setgroups` in signature/snippet | seccomp fix (AppArmor userns, CC #43454) |
| `permission_denied` + read-only command (`ls`, `find`, `grep`, …) | deny rule is too broad |
| other `permission_denied` | add scoped allow rule or narrow deny pattern |

Advisory only. No edits to any config file.

**CLI flags**

```
--scan-history      mine all transcripts instead of the log
--top N             show at most N clusters (default 15)
--verbose           list which sessions/transcripts were reviewed
--include-archive   also read failures.archive.jsonl
--archive           rotate stale records to the archive now, then exit
--retention-days N  override the 7-day default
```

---

### `hooks/session-end.sh` — Fail-safe wrapper

Reads the hook JSON payload from stdin, extracts `transcript_path` using `python3`
(no `jq` dependency), then calls `capture.py`. All output is discarded. Always
exits 0 — a broken audit hook must be invisible to the user.

---

## Record Schema

Each line in `failures.jsonl` / `failures.archive.jsonl` is one JSON object:

```json
{
  "ts":          "2026-07-01T12:34:56.789Z",
  "session_id":  "<uuid>",
  "tool_use_id": "toolu_...",
  "project":     "project-dir-name | [redacted]",
  "cwd":         "/absolute/path   | [redacted]",
  "tool":        "Bash | Read | Edit | ...",
  "kind":        "permission_denied | runtime_failure",
  "signature":   "canonical failure fingerprint — never contains raw values",
  "command":     "tool input, redacted | ls [denied-args] | [denied-path]",
  "snippet":     "error text, redacted, ≤300 chars | [error — details redacted ...]"
}
```

`signature` is always derived from the already-safe `command` and `snippet`
values, never from the raw transcript text.

---

## Critical Invariants

1. **Hook never fails the session.** `session-end.sh` always exits 0 and swallows
   all errors. `capture.py` wraps `archive_stale()` in a bare `try/except`. Nothing
   can propagate a non-zero exit or block I/O at session teardown.

2. **Nothing written without passing the privacy gate.** Every record goes through
   `redact.py` before `append_records()`. The `signature` is built from the safe
   (masked/cleaned) values, never from raw inputs.

3. **Doctor is advisory only.** `doctor.py` and the skill never edit `settings.json`
   or any other config file. Lifting this requires an explicit Phase-2 decision.

4. **Runtime `"permission denied"` ≠ CC permission denial.** `classify()` does not
   match bare `"permission denied"`. Only CC-specific permission-gate markers count.
   `TestClassify` is the regression test for this boundary.

5. **Dedup spans both files.** `append_records()` checks against both the active log
   AND the archive. Archiving a record can never let a later re-scan resurrect it
   into the active log.

6. **Single source of truth for paths.** `lib/common.py` only. Hook and skill both
   import from it.

7. **Archive is move, not delete.** `archive_stale()` appends to the archive before
   rewriting the active log. A crash between the two steps loses nothing.

---

## Test Matrix

```
tests/test_capture.py    — mine_transcript, classify, noise filtering, signature,
                           archive_stale, append_records dedup
tests/test_doctor.py     — cluster, suggest, report output
tests/test_redact.py     — is_denied, mask_command, mask_snippet, redact, clean_snippet
tests/test_manifests.py  — plugin.json, marketplace.json, hooks.json schema validity

tests/fixtures/          — synthetic transcripts (one case per file):
                           seccomp failure, permission denial, noise (cancelled parallel),
                           user interruption, secret-in-command, denylisted path,
                           string toolUseResult, mixed results
```

CI runs Python 3.9 and 3.12 on every push and PR.
