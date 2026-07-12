---
title: sandbox-audit Glossary
last-updated: 2026-07-12
status: current
---

# Glossary

Domain terms used throughout the codebase and documentation. Misreading these
silently produces wrong code — check here when uncertain.

---

**active log** — `~/.claude/sandbox-audit/failures.jsonl`. The file `doctor`
reads by default. Contains records within the current retention window
(`DEFAULT_RETENTION_DAYS = 7`). Distinguished from the archive.

**archive** — `~/.claude/sandbox-audit/failures.archive.jsonl`. The audit trail
for aged-out records. Invariant P7: records are moved here, never deleted. Doctor
reads it with `--include-archive`.

**capture** — the process of mining a transcript and appending new failure records
to the active log. Implemented in `lib/capture.py`, invoked by the hook.

**classification** / **kind** — the two categories a failure can have:
`permission_denied` (a CC permission gate fired) or `runtime_failure` (anything
else, including seccomp/OS errors). See invariant P4 for the boundary. Stored in
the `kind` field of a failure record.

**denylist** — a user-editable list of substrings (`lib/denylist.txt`). If a
record's command, path, cwd, project name, or error text contains a denylisted
substring, the sensitive fields are masked rather than stored verbatim. See
invariant P2 and `lib/redact.py`.

**dedup** — deduplication by `(session_id, tool_use_id)`. `append_records` is
idempotent on this key and checks both the active log and the archive. See
invariant P5.

**doctor** — the diagnosis skill (`lib/doctor.py`, invoked as
`/sandbox-audit:doctor`). Reads the active log, clusters records by signature,
and prints an advisory report. Never edits any config file (invariant P3).

**failure record** — one JSON object in `failures.jsonl` or
`failures.archive.jsonl`. Schema: `ts`, `session_id`, `tool_use_id`, `project`,
`cwd`, `tool`, `kind`, `signature`, `command`, `snippet`. See `ARCHITECTURE.md`
for the full schema and field semantics.

**hook** — the `SessionEnd` hook: `hooks/session-end.sh`. Fires at the end of
every Claude Code session, calls `lib/capture.py` with the transcript path.
Must always exit 0 (invariant P1).

**noise** — transcript entries that should be discarded before classification:
cancelled parallel tool calls (`"cancelled: parallel tool call"`) and
user-interrupted calls (`"[request interrupted by user"`). Filtered by
`is_noise()` in `lib/capture.py`.

**privacy gate** — `lib/redact.py`. Both layers (denylist masking + secret
scrubbing) must run before a record is written to disk. Invariant P2.

**redact** — the act of running a record through the privacy gate. Also the name
of the module (`lib/redact.py`) and its primary function `redact(text)`.

**retention window** — `DEFAULT_RETENTION_DAYS = 7` days. Records older than
this are moved to the archive by `archive_stale`. Configurable via
`doctor --retention-days N`.

**secret scrubbing** — layer 2 of the privacy gate. Strips PEM keys, bearer
tokens, GitHub/GitLab/AWS/Anthropic tokens, and `KEY=value` env assignments from
any text that IS kept. Implemented via `_SECRET_PATTERNS` in `lib/redact.py`.

**session_id** — the UUID identifying a Claude Code session. Derived from the
transcript filename. Part of the dedup key `(session_id, tool_use_id)`.

**signature** — the canonical fingerprint used for clustering. Built by
`_canon()` in `lib/capture.py` from the safe (masked/cleaned) command and error
text — never from raw values (invariant P2). Format:
`permission_denied:<tool>:<canon(command[:80])>` or
`<tool>:<canon(salient_error_line[:140])>`.

**snippet** — the error text stored in a record, post-redaction, truncated to 300
characters. Derived from `toolUseResult.stderr` when present, otherwise from the
`tool_result` content.

**suggestion** — advisory text produced by `doctor.suggest()`. Printed to stdout.
Never auto-applied (invariant P3).

**tool_use_id** — the ID of a specific tool invocation within a session (e.g.
`toulu_01...`). Part of the dedup key. Comes from `tool_use` blocks in the
transcript.

**transcript** — a Claude Code session file at
`~/.claude/projects/<project>/<session-id>.jsonl`. One JSON object per line.
`capture.py` parses `tool_use` and `tool_result` blocks from it.
