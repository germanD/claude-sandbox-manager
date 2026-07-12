---
title: sandbox-audit Task-Driven Index
last-updated: 2026-07-12
status: current
---

# Task-Driven Index

For each task type: which KB files and code files to read, which invariants to
verify, and what the test plan should cover. Load the prescribed files before
starting — reading the code without the invariants is how silent regressions land.

---

## Implement a new failure heuristic

**Goal:** Add a new noise filter, classify rule, or signature pattern to
`lib/capture.py` — for example, a new class of errors to suppress or a new
failure kind.

**Read first:**
1. `kb/properties.md` P1, P2, P4 — the three invariants this code path touches
2. `ARCHITECTURE.md` → Components → `lib/capture.py` — classification rules, signature format, noise filtering
3. `lib/capture.py` — `classify()`, `is_noise()`, `_canon()`
4. `tests/test_capture.py` → `TestClassify` — the regression suite you must extend

**Invariant checkpoints:**
- P4: new classification must not match bare `"permission denied"` as a CC denial
- P2: any new or modified signature must be built from safe (masked/cleaned) values, not raw text
- P1: any new error paths in `main()` must be swallowed

**Test plan:** add a fixture under `tests/fixtures/` and a case in `TestClassify`.

---

## Add a new doctor suggestion

**Goal:** Add a new advisory to `lib/doctor.py` — a new pattern in `suggest()`
or a new cluster-level heuristic.

**Read first:**
1. `kb/properties.md` P3 — suggestions are advisory only; never edit config
2. `ARCHITECTURE.md` → Components → `lib/doctor.py` — clustering, `suggest()` conditions, CLI flags
3. `lib/doctor.py` — `suggest()`, `cluster()`
4. `tests/test_doctor.py` — extend the suggestion coverage

**Invariant checkpoints:**
- P3: the suggestion must be printed text only — no writes to `settings.json` or any file

**Test plan:** add a case in `TestSuggest` or `TestReport` in `tests/test_doctor.py`.

---

## Extend the privacy gate

**Goal:** Add a new secret pattern to `lib/redact.py`, modify denylist masking,
or change what gets scrubbed from snippets.

**Read first:**
1. `kb/properties.md` P2 — privacy beats completeness; signature must use safe values
2. `kb/glossary.md` → denylist, secret scrubbing, privacy gate
3. `ARCHITECTURE.md` → Components → `lib/redact.py`
4. `lib/redact.py` — `_SECRET_PATTERNS`, `is_denied()`, `redact()`, `mask_command()`
5. `tests/test_redact.py` — extend coverage for the new pattern

**Invariant checkpoints:**
- P2: after the change, no raw token/key/path can appear in a stored record
- P2: `signature` must still be built from the masked/scrubbed values

**Test plan:** add a fixture in `tests/fixtures/` containing the new secret form,
add a case in `tests/test_redact.py`. Also run `tests/test_capture.py` to confirm
the redact change doesn't break signature generation.

---

## Change the record schema

**Goal:** Add, remove, or rename a field in the JSON objects written to
`failures.jsonl` / `failures.archive.jsonl`.

**Read first:**
1. `kb/properties.md` P2, P5, P6 — privacy gate, dedup key, single path source
2. `kb/glossary.md` → failure record, session_id, tool_use_id, signature
3. `ARCHITECTURE.md` → Record Schema
4. `lib/capture.py` — `_make_record()`, `append_records()`
5. `lib/doctor.py` — field references in `cluster()` and `suggest()`
6. `tests/test_capture.py`, `tests/test_doctor.py` — update both

**Invariant checkpoints:**
- P5: if you change or remove `session_id` or `tool_use_id`, the dedup key breaks — update `append_records` accordingly
- P2: any new field containing user-supplied text must pass through redact before storage
- P6: if adding a new path constant, add it to `lib/common.py` only

**Test plan:** update existing fixture expectations; add a new fixture if the new
field captures a previously untested case.

---

## Write or fix a test

**Goal:** Add a new unit test, extend an existing suite, or add a fixture
transcript.

**Read first:**
1. `AGENTS.md` → Build & Test — the exact commands CI runs
2. `tests/fixtures/` — existing synthetic transcripts (one case per file)
3. The test file being changed (`test_capture.py`, `test_doctor.py`,
   `test_redact.py`, or `test_manifests.py`)

**Conventions:**
- Each fixture file covers one case; name it after what it exercises (e.g.
  `seccomp-failure.jsonl`, `secret-in-command.jsonl`)
- Use stdlib `unittest` only — no pytest, no network
- Run `python -m unittest discover -s tests -v` to verify

---

## Add a CLI flag to doctor

**Goal:** Add a new `--flag` to `lib/doctor.py`'s argument parser.

**Read first:**
1. `kb/properties.md` P3 — the flag must not trigger any config edits
2. `ARCHITECTURE.md` → Components → `lib/doctor.py` → CLI flags
3. `lib/doctor.py` — `argparse` setup and `main()`
4. `tests/test_doctor.py` — add a case exercising the new flag

**Note:** Update `ARCHITECTURE.md` → CLI flags table after adding the flag.

---

## Debug a hook failure

**Goal:** The hook ran but produced no records (or wrong records). Diagnose why.

**Read first:**
1. `kb/properties.md` P1 — the hook swallows errors silently; failures are invisible by design
2. `kb/properties.md` P2, P4 — redaction or misclassification may be the cause
3. `ARCHITECTURE.md` → Data Flow — full pipeline from hook to log
4. `hooks/session-end.sh` — how the transcript path is extracted and passed
5. `lib/capture.py` `main()` — what happens to each transcript

**Diagnosis steps:**
1. Run `python3 lib/capture.py <transcript_path>` manually to see output (errors
   will surface because you're not inside the hook's `>/dev/null`).
2. Check whether records exist in `failures.jsonl` but are redacted (denylist match).
3. Check whether records exist but are classified as noise — add `-v` style prints
   temporarily; do not land debug prints in production code.

---

## Design or evaluate a Phase-2 feature

**Goal:** Assess whether a new feature fits the architecture before starting
implementation.

**Read first:**
1. `kb/spec.md` — non-goals; invariants that Phase-2 must respect or explicitly relax
2. `kb/properties.md` — all seven invariants (P3 especially: any auto-apply feature changes this)
3. `docs/phase2-design.md` — the three existing v0.2.0 candidates and their trade-offs
4. `ARCHITECTURE.md` → Data Flow — what the current pipeline looks like
5. `ONBOARDING.md` → Honest caveats — constraints still relevant for Phase 2
