# AGENTS.md — sandbox-audit: Guidance for AI Coding Agents

This file provides context for AI coding agents (Claude Code, and others)
working on the `sandbox-audit` plugin.

**Key references** (read these before making architectural decisions):

- `kb/index.md` — Knowledge Base index: spec, invariants, glossary, task-driven guide.
- `ARCHITECTURE.md` — as-built data flow, component descriptions, record schema.
- `docs/phase2-design.md` — design sketches for the three v0.2.0 candidates.
- `ONBOARDING.md` — contributor quick-start and historical design notes.

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
kb/
├── index.md            # KB master routing guide
├── spec.md             # product spec: what it does, who for, non-goals
├── properties.md       # invariants P1–P7 (authoritative)
├── glossary.md         # domain terms
└── by-task.md          # task-driven index: which files to read per task
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

## Critical Invariants

The seven invariants are defined and maintained in [`kb/properties.md`](kb/properties.md).
That file is authoritative — if it conflicts with prose elsewhere, the KB wins.

| # | Name | Core rule |
|---|---|---|
| P1 | Hook fail-safety | `session-end.sh` always exits 0; no code path may propagate a non-zero exit |
| P2 | Privacy-gate completeness | Nothing written to disk without passing `redact.py`; `signature` built from safe values only |
| P3 | Doctor is advisory | `doctor.py` never edits `settings.json` or any config file |
| P4 | Classification boundary | Bare `"permission denied"` is a runtime failure, not a CC permission denial |
| P5 | Dedup spans both files | `append_records` checks active log AND archive; re-scans never double-count |
| P6 | Single path source | `lib/common.py` only; hook and skill never hardcode paths |
| P7 | Archive is move-not-delete | Records appended to archive before active log is rewritten |

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

## Agent Roles

| Agent | Responsibility |
|---|---|
| `pmo` | Milestone/PLAN.md sync, PR label verification, release prep — no code |
| `capture-specialist` | Transcript parsing, classification, noise filtering, signature generation, persistence/dedup |
| `doctor-specialist` | Clustering heuristics, suggestion text, CLI flags, `--scan-history` loading path |
| `redact-guardian` | Privacy gate changes: secret patterns, denylist masking, any code touching `redact.py` |

### pmo

Spawn for any project-admin task: labeling PRs, syncing PLAN.md with GitHub,
closing milestones, or auditing unlabeled history. Does not write code — hands
implementation back to the main agent. See `.claude/agents/pmo.md`.

### capture-specialist

Spawn when implementing changes to `lib/capture.py`: new failure classifications,
noise filters, signature patterns, or changes to `append_records` / `archive_stale`.

- Must preserve P1 (hook fail-safety), P2 (privacy gate), P4 (classification boundary), P5 (dedup)
- Any signature change must use safe (masked/cleaned) values only — never raw transcript text
- Consult `kb/by-task.md` → "Implement a new failure heuristic" for the prescribed reading order
- Changes to `append_records` or `archive_stale` must verify P5 and P7

### doctor-specialist

Spawn when modifying `lib/doctor.py`: new `suggest()` conditions, clustering
changes, new CLI flags, or changes to the `--scan-history` loading path.

- Suggestions are advisory only — P3 forbids any config-editing behavior
- Clustering depends on `signature`; changes to signature format in `capture.py` are a breaking dependency
- Consult `kb/by-task.md` → "Add a new doctor suggestion" or "Add a CLI flag to doctor"

### redact-guardian

Spawn when touching `lib/redact.py`, `lib/denylist.txt`, or any code that
intersects the privacy gate.

- Privacy beats completeness (P2): if in doubt, mask or drop
- New secret patterns need a fixture in `tests/fixtures/` and a case in `tests/test_redact.py`
- Denylist behavior changes are user-visible — bump `version` in `.claude-plugin/plugin.json`
- Signature must always be built from the masked/scrubbed values, never raw inputs

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
- Every PR must carry at least one area label (`capture`, `doctor`, `redact`,
  `hook`, `archive`, `plugin`, `tests`); inherit from the linked issue or apply directly.
- Do not merge your own PR — wait for approval.

### Roadmap
Open work is tracked in `PLAN.md` with one checkbox per GitHub issue.
PMO keeps `PLAN.md` and milestones in sync — see `.claude/agents/pmo.md`.

## What's Not Here Yet

This is a Phase-1 MVP. Deliberately out of scope for now:

- No automatic editing of `settings.json` (diagnosis only — see invariant P3).
- No cross-machine sync of the failures log.
- No UI beyond the `doctor` skill's text report.
