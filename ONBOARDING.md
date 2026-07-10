# ONBOARDING.md — sandbox-audit: contributor quick-start

> **Status: Phase-1 MVP shipped (v0.1.3).** The sections below are a contributor
> on-ramp. For architecture and implementation detail see `ARCHITECTURE.md`;
> for agent/contributor conventions see `AGENTS.md`.

---

## What this is

A Claude Code plugin that mines session transcripts for **failing tool calls** and
**permission denials**, clusters recurring patterns, and suggests config fixes.

Think "`/doctor`, but it learns from what actually failed, and runs automatically
across sessions."

---

## Motivation (why it exists)

On some setups the same failures repeat silently, session after session, with no
feedback loop:

1. **Broken seccomp sandbox** — sandboxed `Bash` dies with
   `apply-seccomp: write /proc/self/setgroups: Permission denied` (CC #43454).
2. **Over-broad deny rules** — `Bash(*priv-misc*)` blocks even read-only
   `ls`/`find` that merely mentions the path.

Nothing was aggregating these. `sandbox-audit` closes the loop.

---

## Core insight

There is no cross-session daemon in Claude Code. Two facts make a "service"
work without one:

1. Every session writes a transcript to `~/.claude/projects/<project>/<session-id>.jsonl`.
2. Hooks fire per-session and can append to a shared file.

So the architecture is **append-only shared log + periodic aggregator** — not a
daemon. See `ARCHITECTURE.md` for the full data flow.

---

## Quick start

### Install the plugin

```bash
claude --plugin-dir /path/to/claude-sandbox-manager
/reload-plugins
claude plugin validate /path/to/claude-sandbox-manager
```

### Run the test suite

```bash
python -m py_compile lib/*.py                  # syntax check
python -m unittest discover -s tests -v        # full suite
```

No dependencies beyond the Python 3.9+ standard library.

### Mine your existing history (before the hook has run)

```bash
python3 lib/doctor.py --scan-history --verbose
```

### Fire the hook manually (test it without ending a session)

```bash
echo '{"transcript_path":"/path/to/session.jsonl"}' | bash hooks/session-end.sh
python3 lib/doctor.py
```

### Run the doctor skill

```
/sandbox-audit:doctor
```

---

## Validation targets (achieved by Phase-1)

The tool was considered "working" when, run against the machine's history, it
independently surfaced:

- The recurring `apply-seccomp` seccomp failure → the AppArmor / userns fix.
- The `ls …priv-misc…` denials → "deny rule is too broad; narrow the pattern."

Both were verified. The seccomp root cause (`applyPath` being ignored) was also
identified and documented in `lib/doctor.py`'s `suggest()` function.

---

## Phase 2 candidates

See `docs/phase2-design.md` for design sketches of the three v0.2.0 candidates:
real-time failure flagging, a cross-session aggregator, and gated auto-apply of
`settings.json` diffs.

---

## Original design notes

The original pre-code architecture sketch (including the CC primitives reference
table, caveats, and settings precedence notes) has been preserved below for
historical context. The implemented architecture differs in a few details: the
data directory is `~/.claude/sandbox-audit/` (not `~/.claude/audit/`); real-time
hooks were not implemented in Phase 1 (transcript mining only); the plugin skill
is `/sandbox-audit:doctor` (not `/audit:doctor`).

<details>
<summary>Original design notes (pre-code)</summary>

### How it maps to real Claude Code primitives

| Need | Primitive | Notes |
|---|---|---|
| Capture failures | hooks (PostToolUse / failure / permission-denied / SessionEnd) | payload lacks exit code/output — mine the transcript |
| Recover real outcomes | parse `transcript_path` JSONL in SessionEnd hook | plaintext JSONL, one event per line |
| Cross-session "service" | `/schedule` routine (cron) | no true daemon exists; this is the substitute |
| Extend `/doctor` | ship own `/audit:doctor` skill | `/doctor` itself is not pluggable |
| Suggest + apply fixes | agent emits structured settings diffs | apply gated on approval |
| Packaging | one plugin: hooks + skill + agent + routine | single `.claude-plugin/plugin.json` manifest |

Settings precedence (highest→lowest): managed → CLI args → project local →
project → user → defaults.

### Honest caveats (still relevant for Phase 2)

- **No daemon** — poll-on-cron, not live. Acceptable for config tuning.
- **Transcripts are plaintext and may contain secrets.** Redaction + a
  path/command denylist must be designed in from line one. Phase-1 does this;
  any cloud or cross-machine phase must inherit it.
- Real-time hook event names (exact names for runtime-failure vs.
  permission-denied) should be pinned against the installed CC version before
  relying on them. The transcript-mining core does not depend on them.
- `/doctor` is not extensible — ship a parallel skill, not a hook into it.

</details>
