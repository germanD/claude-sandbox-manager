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

*(file issues to populate this section)*

---

## v0.2.0 — Phase 2 (to be scoped)

Candidates from "What's Not Here Yet" in AGENTS.md — none are committed
until the user files and milestones the corresponding issues:

- [ ] Suggested config auto-application (settings.json edits, user-approved — lift invariant #3)
- [ ] Cross-machine sync of `failures.jsonl`
- [ ] Richer UI beyond the `doctor` skill text report
