# AGENTS.md — sandbox-audit: Guidance for AI Coding Agents

This file provides context for AI coding agents (Claude Code, and others)
working on the `sandbox-audit` plugin.

## Project Overview

`sandbox-audit` is a Claude Code plugin that mines Claude Code session
transcripts for failing tool calls and permission denials, clusters recurring
failures, and suggests sandbox/permission config fixes. It has two moving parts:

- A **`SessionEnd` hook** (`hooks/session-end.sh` → `lib/capture.py`) that mines
  the just-ended session transcript and appends redacted failure records to a
  shared log at `~/.claude/sandbox-audit/failures.jsonl`.
- A **`doctor` skill** (`skills/doctor/SKILL.md` → `lib/doctor.py`) that clusters
  the captured failures and prints **advisory** fix suggestions.

## Build & Test

The project is **Python standard library only** — there are no third-party
dependencies and no build step. CI runs on Python 3.9 and 3.12.

```bash
python -m py_compile lib/*.py                  # syntax check (matches CI)
python -m unittest discover -s tests -v        # run the test suite (matches CI)
```

- Tests use the stdlib `unittest` runner and fixture transcripts under
  `tests/fixtures/*.jsonl`. No pytest, no network, no external tools.
- Every non-trivial change to `lib/` should come with or update a test.

## Project Structure

```
.claude-plugin/
├── plugin.json         # plugin manifest (name, version, keywords)
└── marketplace.json    # local dev marketplace pointing at ./
hooks/
├── hooks.json          # registers the SessionEnd hook
└── session-end.sh      # fail-safe wrapper: reads hook JSON, calls capture.py
lib/
├── capture.py          # transcript miner: parse → classify → redact → append
├── common.py           # shared paths/constants (DATA_DIR, FAILURES_PATH, ARCHIVE_PATH)
├── denylist.txt        # user-editable substring denylist (privacy gate)
├── doctor.py           # cluster failures + advisory suggestions (skill backend)
└── redact.py           # denylisting + secret scrubbing (privacy layer)
skills/doctor/
└── SKILL.md            # the /doctor skill: how to run + present doctor.py
tests/
├── fixtures/*.jsonl    # synthetic transcripts exercising each code path
└── test_*.py           # unittest suites (capture, doctor, redact, manifests)
```

## Critical Invariants — Read Before Making Changes

### 1. The audit hook must NEVER fail a session
`hooks/session-end.sh` is fail-safe by contract: it runs `set -u`, swallows all
errors, and always `exit 0`. A broken audit hook must be invisible to the user —
it must not break, delay, or surface errors during a session's teardown. Never
introduce a code path that can propagate a non-zero exit or block on I/O.

### 2. Nothing is persisted until it passes through `redact.py`
Privacy beats completeness. Every record written to `failures.jsonl` must go
through the two-layer privacy gate in `lib/redact.py`:

- **Denylist** (`is_denied` / `denylist.txt`): if a record's command, path, cwd,
  or error text contains a denylisted substring (e.g. `priv-misc`, always on),
  the sensitive parts are **masked** (not the raw values persisted). The record
  keeps only its learnable *shape*.
- **Secret scrubbing** (`redact` / `_SECRET_PATTERNS`): tokens, keys, auth
  headers, and `KEY=value` secrets are scrubbed from any text that IS kept.

The stored `signature` must be built from the **safe (masked/cleaned)** values,
never the raw command or error — so it clusters without ever leaking.

### 3. `doctor` is advisory only
`lib/doctor.py` and the `doctor` skill diagnose and suggest. This MVP **never
edits `settings.json`** or any config file. Do not add auto-fix behavior without
an explicit decision to change that contract; the SKILL.md says so too.

### 4. Do not classify runtime failures as permission denials
Classification in `capture.py` deliberately does **not** match a bare
`"permission denied"`. The seccomp/sandbox stderr
(`apply-seccomp: ... Permission denied`) is a *runtime* failure, not a Claude
Code permission gate. Only the specific permission-gate markers
(`_PERM_MARKERS`, and the `"permission to use ... has been denied"` deny-rule
message) count as `permission_denied`. There is a regression test guarding this
(`tests/test_capture.py::TestClassify`).

### 5. Records are deduped by `(session_id, tool_use_id)`
`append_records` is idempotent on that key so re-running the hook or
`--scan-history` never double-counts a failure. Preserve this when changing the
record schema or persistence path.

### 6. Fixed, predictable data directory
Both the hook and the skill agree on `~/.claude/sandbox-audit/failures.jsonl`
(active log) and `~/.claude/sandbox-audit/failures.archive.jsonl` (audit trail)
via `lib/common.py` (they must not depend on plugin-only env vars being exposed
to skills). Change these paths in one place only.

### 7. Aged-out records are MOVED to the audit trail, never deleted
`capture.archive_stale` rolls records older than `DEFAULT_RETENTION_DAYS` out of
the active log into `failures.archive.jsonl` so `doctor` stays focused on what's
current. Preserve these properties:
- **Move, not delete.** Stale records are appended to the archive *before* being
  dropped from the active log — nothing is lost even if the rewrite fails.
- **Fail-safe.** `main` calls `archive_stale` inside a `try/except` that swallows
  everything; it must never break the capture / SessionEnd-hook path (invariant #1).
- **Dedup spans both files.** `append_records` dedups against the active log AND
  the archive, so a re-scan of an old transcript can never resurrect an archived
  record into the active log (extends invariant #5).
- **Undatable records stay active.** Records with a missing/unparseable `ts` are
  never archived — we don't age out something we can't date.
- `doctor --archive` forces a rotation now; `doctor --include-archive` reports
  over the active log + trail together.

## Code Conventions

- **Stdlib only.** Do not add third-party dependencies. If you reach for one,
  find a stdlib equivalent instead.
- **Python 3.9 compatible.** CI tests 3.9 and 3.12 — no `match` statements, no
  3.10+ typing syntax, no walrus-only-in-3.11 features.
- **Fail-safe over feature-complete** in the hook path: swallow, log to
  `/dev/null`, exit 0.
- Keep `lib/` modules importable both as a module and as a script (they insert
  their own dir on `sys.path`; preserve the `# noqa: E402` imports).
- Match the existing comment density: each module leads with a docstring
  explaining its privacy/safety contract. Keep that when editing.
- Bump `version` in `.claude-plugin/plugin.json` for user-visible behavior
  changes (the git history follows `v0.1.x`).

## Git & GitHub Workflow

### Never commit directly to `main`
All work happens on a feature branch (`feat/`, `fix/`, `docs/`, `refactor/`).
The primary working directory stays on `main` as a clean reference; agents use a
feature branch or an isolated worktree for implementation.

### Force-push policy
Force-pushing is reserved for the human. Agents must not run `git push --force`,
`git push -f`, or `git push --force-with-lease` — even when asked. If a workflow
appears to require it, surface the proposed command and let the human run it.

### Pull requests
- Push only after the human has authorised it for the task at hand.
- Reference the issues a PR closes with `Closes #N` / `Fixes #N` in the body.
- Include a test plan showing `py_compile` and the `unittest` run, and evidence
  they actually passed.
- Do not merge your own PR — wait for approval.

## What's Not Here Yet

This is a Phase-1 MVP. Deliberately out of scope for now:

- No automatic editing of `settings.json` (diagnosis only — see invariant #3).
- No cross-machine sync of the failures log.
- No UI beyond the `doctor` skill's text report.
