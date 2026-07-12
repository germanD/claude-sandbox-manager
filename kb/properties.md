---
title: sandbox-audit Invariants and Properties
last-updated: 2026-07-12
status: authoritative
---

# Invariants and Properties

These are correctness constraints that must hold at all times. If code
contradicts a property, the code is wrong — not this document.

---

## P1: Hook Fail-Safety

**The audit hook must NEVER fail or delay a session.**

`hooks/session-end.sh` is fail-safe by contract: it runs `set -u`, redirects all
output to `/dev/null`, and always exits 0. `lib/capture.py` wraps `archive_stale`
in a bare `try/except` that swallows everything.

**Constraint:** Never introduce a code path in `session-end.sh` or `capture.py`
that can propagate a non-zero exit code or block on I/O. A broken audit hook must
be invisible to the user — it must not surface errors during session teardown.

---

## P2: Privacy-Gate Completeness

**Nothing is persisted until it passes through `redact.py`.**

Privacy beats completeness. Every record written to `failures.jsonl` must pass
through both layers of `lib/redact.py`:

- **Denylist** (`is_denied` / `denylist.txt`): if the command, path, cwd, project
  name, or error text contains a denylisted substring, sensitive fields are
  **masked** — the record keeps only its learnable *shape* (`tool`, `kind`,
  masked command), never the raw values.
- **Secret scrubbing** (`redact` / `_SECRET_PATTERNS`): tokens, keys, auth
  headers, and `KEY=value` secrets are scrubbed from any text that IS kept.

**Constraint:** The stored `signature` must be built from the **safe
(masked/cleaned)** values, never from raw transcript text. Any new field added to
the record must either pass through redact or be verifiably non-sensitive.

---

## P3: Doctor Is Advisory Only

**`lib/doctor.py` and the `doctor` skill never edit any config file.**

This MVP provides diagnosis and suggestion — no auto-apply. `SKILL.md` states
this contract explicitly.

**Constraint:** Do not add config-editing behavior without an explicit Phase-2
decision to change this contract. Any suggestion output is printed text only.

---

## P4: Classification Boundary

**Bare `"permission denied"` is a runtime failure, not a CC permission denial.**

`classify()` in `lib/capture.py` deliberately does not match a bare
`"permission denied"` string. The seccomp/sandbox stderr
(`apply-seccomp: ... Permission denied`) is a *runtime* failure caused by the OS,
not a Claude Code permission gate. Only the specific CC-gate markers
(`_PERM_MARKERS` and the `"permission to use ... has been denied"` deny-rule
message) count as `permission_denied`.

**Constraint:** Never broaden `_PERM_MARKERS` to match raw `"permission denied"`.
`tests/test_capture.py::TestClassify` is the regression guard for this boundary.

---

## P5: Dedup Spans Both Files

**`append_records` is idempotent on `(session_id, tool_use_id)` across both the
active log and the archive.**

Re-running the hook or `--scan-history` must never double-count a failure.
Archiving a record must not allow a later re-scan to resurrect it into the active
log.

**Constraint:** When changing `append_records`, `archive_stale`, or the
persistence path, verify that the dedup check covers both
`failures.jsonl` AND `failures.archive.jsonl`.

---

## P6: Single Source of Truth for Paths

**`lib/common.py` is the only place where data paths are defined.**

Both the hook and the skill import `DATA_DIR`, `FAILURES_PATH`, and `ARCHIVE_PATH`
from `lib/common.py`. They must not depend on plugin-only environment variables
being exposed to skills.

**Constraint:** Never hardcode a path in `session-end.sh`, `capture.py`,
`doctor.py`, or anywhere else. Change paths in `common.py` only.

---

## P7: Archive Is Move-Not-Delete

**`archive_stale` appends to the archive *before* rewriting the active log.**

Stale records (older than `DEFAULT_RETENTION_DAYS`) are moved to
`failures.archive.jsonl` so that `doctor` stays focused on recent failures.
The move is crash-safe:

- Records are appended to the archive first.
- The active log is rewritten atomically via a temp file + `os.replace()`.
- A crash between the two steps is safe — records are in the archive, and dedup
  (P5) prevents re-ingestion if the hook runs again.
- Records with a missing or unparseable `ts` are never archived — we cannot date
  them.

**Constraint:** Do not delete records from either file without appending to the
other first. Preserve the fail-safe wrapping in `capture.main()` (P1).
