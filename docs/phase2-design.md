# Phase 2 design notes — sandbox-audit

These are design sketches for the three v0.2.0 candidates listed in `PLAN.md`.
None are committed until the corresponding issues are filed and milestoned.

For the current Phase-1 MVP architecture see `ARCHITECTURE.md`.

---

## Candidate A — Real-time failure flagging

**What:** fire a hook on each tool failure in real time rather than mining the
transcript at `SessionEnd`.

**Motivation:** `SessionEnd` mining is reliable but delayed — failures are only
captured after the session ends. Real-time flagging could surface a recurring
problem mid-session, giving the user a chance to act before the pattern repeats.

**Relevant hook events**

Claude Code exposes per-tool-call hooks. Exact event names should be verified
against the installed CC version:

| Event (approximate) | When it fires |
|---|---|
| `PostToolUse` (failure variant) | after a tool call returns an error |
| `PermissionDenied` | when CC's permission gate rejects a tool call |

**Fundamental constraint:** real-time hook payloads do not include exit code,
stdout, or stderr — only that a tool ran (or was denied) and its input. The
`toolUseResult` enrichment that `capture.py` uses is only available in the
transcript. So real-time hooks can *flag* a failure immediately but cannot
reconstruct the full error text.

**Design options**

| Option | Trade-off |
|---|---|
| Real-time hooks as a fast-path flag only; `SessionEnd` mining is still the canonical record | Simple; no payload gap; only value added is earlier notification |
| Real-time hooks write a partial record; `SessionEnd` back-fills the error text | More complex merge logic; dedup must handle partial vs full records |
| Replace `SessionEnd` mining with real-time hooks | Loses the error text (payload gap) — not viable |

**Recommended approach:** option 1. The real-time hook writes a stub record
(or just increments a counter), and `SessionEnd` mining supersedes it with a
full record. The dedup key (`session_id`, `tool_use_id`) already supports this —
the stub and the full record share the same `tool_use_id`.

**Open design questions**
- What does the in-session notification look like? A transient message? An
  ambient counter? Nothing visible (flag only, report later)?
- Which CC version introduced stable `PostToolUse` failure / `PermissionDenied`
  event names? Pin the version before depending on them.
- Is the added complexity worth it, given that `SessionEnd` already captures
  everything reliably?

---

## Candidate B — Cross-session aggregator on a cron schedule

**What:** run the doctor analysis automatically on a schedule (e.g. daily) and
surface a summary without the user having to invoke `/sandbox-audit:doctor`.

**Motivation:** the current model is pull-only. A user who doesn't remember to
run `/doctor` never sees a recurring pattern. A scheduled aggregator makes the
feedback loop truly automatic.

**The Claude Code primitive:** `/schedule` routines (cron-based cloud agents).
There is no persistent daemon. The aggregator runs as a cloud agent on a
schedule, so it can access the local `failures.jsonl` only if it runs on the
same machine via a local hook or script — not via a remote cloud agent.

**Realistic options**

| Option | Notes |
|---|---|
| Local cron job / systemd timer calling `doctor.py` | Simple; no CC primitives; writes a report file the user can check |
| `PreCompact` or `SessionStart` hook that calls `doctor.py` and prints a banner | Shows a summary at the start of each session; no external scheduler needed |
| CC `/schedule` routine (cloud agent) | Only viable if the log is synced to a cloud location — see Candidate C |

**Recommended approach for Phase 2:** a `SessionStart` hook that calls `doctor.py`
and, if there are new clusters since the last run, prints a short banner (e.g.
"sandbox-audit: 3 recurring failures since last week — run /sandbox-audit:doctor
for details"). This requires no external scheduler and no cloud access.

**State needed:** a "last reported" timestamp stored in `DATA_DIR` so the
`SessionStart` hook only prints a banner when there are *new* clusters, not on
every session start.

**Open design questions**
- Where does the banner appear? `SessionStart` hook output goes to the session
  preamble — is that visible/useful?
- What is the "new cluster" threshold? Any new cluster? Only clusters with count
  ≥ N? Only `permission_denied` clusters?
- Should the banner suppress itself after being shown N times for the same cluster
  (to avoid nagging)?

---

## Candidate C — Gated auto-apply of `settings.json` diffs

**What:** when `doctor.py` identifies a recurring failure that maps to a concrete
settings change, generate a `settings.json` patch and offer to apply it with a
single user approval. This lifts invariant #3 (advisory only).

**Motivation:** the current `suggest()` output tells the user *what* to change
but requires them to edit `settings.json` by hand. For common patterns (too-broad
deny rule, missing allow for a safe command) the fix is mechanical.

**Scope of "safe" auto-applies**

Not all fixes are equally safe to automate:

| Fix | Risk level | Notes |
|---|---|---|
| Add `allow` rule for a read-only command (`ls`, `grep`, …) | Low | Narrow, reversible |
| Narrow an over-broad `deny` pattern | Medium | Must not accidentally widen the deny surface |
| Add `allow` rule for a non-read-only command | Medium | Requires user judgement |
| Modify `sandbox.*` settings | High | System-level; wrong value breaks sandboxed Bash |

**Which `settings.json`?**

Claude Code has a settings precedence hierarchy:

```
managed → CLI args → project local (.claude/settings.local.json)
        → project (.claude/settings.json)
        → user (~/.claude/settings.json)
        → defaults
```

The right target depends on the failure's scope:
- Failure in a specific project → project `settings.json`
- Failure across many projects → user `~/.claude/settings.json`
- `managed` files are never auto-edited

**Patch format**

The patch should be a structured diff (not a raw string) so the apply step can
be reviewed and is idempotent:

```json
{
  "target": "user | project",
  "target_path": "~/.claude/settings.json",
  "operation": "add_allow | narrow_deny",
  "before": null,
  "after": { "permissions": { "allow": ["Bash(ls *)"] } }
}
```

**UX design constraint:** the approval gate must be explicit. The patch is shown
to the user in full before anything is written. A single keystroke "apply" is
acceptable; anything silent is not.

**Open design questions**
- Which failures reliably map to a single unambiguous fix? Build a conservative
  allowlist of auto-applicable patterns; leave the rest as advisory.
- Where does the approval UX live? In the `/doctor` skill output (a follow-up
  prompt)? In a separate `/sandbox-audit:apply` skill?
- How does the apply step handle conflicts (e.g. a rule already exists that
  partially overlaps)?
- Should auto-applied changes be logged so they can be reviewed or rolled back?

---

## Build order recommendation

Given the three candidates, the natural sequencing is:

1. **B (SessionStart banner)** — lowest complexity, no new invariants, closes the
   feedback-loop gap without requiring the user to remember `/doctor`.
2. **A (real-time flagging)** — optional fast-path layer on top of B; worth it only
   if in-session notification proves valuable in practice.
3. **C (auto-apply)** — highest risk and complexity; implement only after B has
   validated that the cluster → fix mapping is accurate enough to trust.
