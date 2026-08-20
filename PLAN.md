# PLAN.md — sandbox-audit roadmap

Tracks open work per milestone. PMO keeps this file in sync with GitHub
issues (see `.claude/agents/pmo.md`). One checkbox per issue; tick when
the issue closes; move orphaned items to a later milestone on close.

---

## v0.1.x — Phase-1 MVP: polish & maintenance

Incremental improvements to the current capture → redact → doctor → archive
pipeline. No new subsystems; feature scope is fixed by Phase-1 invariants.

### Shipped

- [x] #1 Add MIT license and full README
- [x] #2 Add sandbox-audit plugin (Phase-1 MVP)
- [x] #3 Add AGENTS.md agent guidance + thin CLAUDE.md pointer
- [x] #4 Add age-based archiving: roll stale failures to audit trail (v0.1.3)

### Open

- [x] #11 test: TestPersistenceDedup does not isolate common.ARCHIVE_PATH
- [x] #12 test: no integration tests for doctor.main() CLI argument paths
- [x] #13 test: capture.main() entry point and archive-swallow path have no test
- [x] #14 capture: mine_transcript silently drops tool name when tool_use_id has no match
- [x] #15 capture: _salient_line returns bare 'exit code N' when that is the entire error text

---

## v0.2.0 — Phase 2: feedback loop automation and session scope isolation

### Candidate B — SessionStart banner

- [x] #7 Add SessionStart hook: banner when new failure clusters are detected

### Hierarchical session scope

- [x] #8 Design: hierarchical session scope for failures log *(resolve design questions first)*
- [x] #9 capture: write to project-scoped failures log based on session CWD
- [x] #10 doctor: scope-aware log loading and --global flag

### Doctor UX improvements

- [ ] #18 doctor: acknowledge/dismiss a failure cluster as acted-upon

### Parking lot (not yet filed)

- [ ] Candidate A — Real-time failure flagging (PostToolUse fast-path)
- [ ] Candidate C — Gated auto-apply of settings.json diffs (lifts P3)
- [ ] Cross-machine sync of `failures.jsonl`
