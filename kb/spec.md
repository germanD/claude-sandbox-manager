---
title: sandbox-audit Product Specification
last-updated: 2026-07-12
status: current
---

# Product Specification

## Problem

On some Claude Code setups the same tool failures repeat silently, session after
session, with no feedback loop:

1. **Broken seccomp sandbox** — sandboxed `Bash` dies with
   `apply-seccomp: write /proc/self/setgroups: Permission denied` (CC #43454).
2. **Over-broad deny rules** — a rule like `Bash(*priv-misc*)` blocks even
   read-only `ls`/`find` that merely mention the path.

Nothing aggregated these across sessions. `sandbox-audit` closes the loop.

## Core Insight

There is no cross-session daemon in Claude Code. Two facts make a service work
without one:

1. Every session writes a transcript to `~/.claude/projects/<project>/<session-id>.jsonl`.
2. Hooks fire per-session and can append to a shared file.

The architecture is therefore **append-only shared log + periodic aggregator** —
not a daemon.

## What It Does

Two components work together:

**`SessionEnd` hook** (`hooks/session-end.sh` → `lib/capture.py`): fires at the
end of every session, mines the just-ended transcript for failing tool calls and
permission denials, passes each record through a privacy gate, and appends it to
a shared log at `~/.claude/sandbox-audit/failures.jsonl`.

**`/sandbox-audit:doctor` skill** (`skills/doctor/SKILL.md` → `lib/doctor.py`):
reads the log, groups failures by canonical fingerprint (signature), and prints a
ranked advisory report with suggested config fixes. The report is read-only —
nothing is ever auto-applied.

## Target User

A Claude Code user who notices recurring tool failures and wants to understand
what's failing and why, without manually inspecting transcripts.

## Non-Goals (Phase 1)

- No automatic editing of `settings.json` — diagnosis and suggestion only.
  (See invariant P3 and `docs/phase2-design.md` for the Phase-2 design.)
- No cross-machine sync of the failures log.
- No real-time alerting during a session — transcript mining only.
- No UI beyond the `doctor` skill's text report.

## Validation Targets (achieved by Phase 1)

The tool was considered working when, run against the machine's history, it
independently surfaced:

- The recurring `apply-seccomp` seccomp failure → the AppArmor / userns fix.
- The `ls …priv-misc…` denials → "deny rule is too broad; narrow the pattern."

Both were verified. The seccomp root cause (`applyPath` being ignored) was also
identified and documented in `lib/doctor.py`'s `suggest()` function.

## Phase 2 Candidates

See `docs/phase2-design.md` for design sketches of the three v0.2.0 candidates:
real-time failure flagging, a cross-session aggregator, and gated auto-apply of
`settings.json` diffs.
