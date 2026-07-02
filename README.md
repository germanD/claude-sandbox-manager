# sandbox-audit

[![CI](https://github.com/germanD/claude-sandbox-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/germanD/claude-sandbox-manager/actions/workflows/ci.yml)

A Claude Code plugin that mines session transcripts for **failing tool calls**
and **permission denials**, clusters the recurring ones, and suggests
sandbox/permission config fixes.

Think "`/doctor`, but it learns from what actually failed across your sessions."

> Status: **Phase-1 MVP**. Local only — nothing leaves your machine. No
> auto-apply of config; suggestions are advisory.

## Why

On some setups the same failures repeat silently, session after session, with no
feedback loop. Two motivating examples:

1. **Broken seccomp sandbox** — sandboxed `Bash` dies with
   `apply-seccomp: write /proc/self/setgroups (... CAP_SYS_ADMIN): Permission denied`
   (Claude Code #43454).
2. **Over-broad deny rules** — a deny pattern like `Bash(*priv-misc*)` blocks even
   read-only `ls`/`find` that merely mention the path.

Nothing aggregates these. `sandbox-audit` closes the loop.

## How it works

```
SessionEnd hook ─▶ hooks/session-end.sh ─▶ lib/capture.py <transcript>
                                              parse JSONL, find is_error:true,
                                              redact + denylist, dedup
                                              ▼
                            ~/.claude/sandbox-audit/failures.jsonl
                                              ▲ reads
       /sandbox-audit:doctor ─▶ lib/doctor.py  cluster + suggest (advisory)
```

The reliable backbone is **transcript mining**: a `SessionEnd` hook reads the
session's `transcript_path` and extracts real outcomes from the JSONL (tool
failures are flagged with `is_error: true`). It does **not** depend on real-time
failure-hook events, whose names/payloads vary by version.

## Install (development)

```bash
claude --plugin-dir /path/to/claude-sandbox-manager
/reload-plugins        # after edits
claude plugin validate /path/to/claude-sandbox-manager
```

## Usage

Run the doctor skill any time:

```
/sandbox-audit:doctor
```

On a fresh install (before any session has ended) the captured log is empty —
mine your existing history directly:

```bash
python3 lib/doctor.py --scan-history
```

`--scan-history` reviews every transcript on disk (all projects, all sessions —
including other live ones, up to what they have flushed), not just the current
session. Add `--verbose` to list exactly which sessions were reviewed, with
per-session failure counts (denylisted project names shown as `[redacted]`):

```bash
python3 lib/doctor.py --scan-history --verbose
```

## Privacy

Redaction and denylisting are built in from line one:

- **Denylist** (`lib/denylist.txt`, plus the always-on `priv-misc` default): any
  failure whose command, path, cwd, or error text matches is **masked** (command
  and snippet redacted, project/cwd shown as `[redacted]`) — the failure shape is
  kept as a learnable signal, but no private path or content is written to the log.
- **Redaction** (`lib/redact.py`): secret-shaped substrings (tokens, API keys,
  `Authorization` headers, PEM private keys, `*_SECRET=`/`*_TOKEN=` assignments)
  are scrubbed from anything that is kept. Snippets are truncated.

The MVP is fully local. Redaction lands now so any later cross-session /
cloud-aggregation phase inherits it.

## Testing

Pure-stdlib `unittest`, no dependencies. Fixtures in `tests/fixtures/` are tiny
synthetic transcripts, one per case (seccomp failure, permission denial, user
rejection, cancelled-parallel noise, secret-in-command, denylisted path, mixed
results, string `toolUseResult`).

```bash
python3 -m unittest discover -s tests -v
```

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.9 and 3.12, plus a
byte-compile syntax check, on every push and PR. The manifest tests also
validate `plugin.json` / `marketplace.json` / `hooks.json`.

## Layout

```
sandbox-audit/
├── .claude-plugin/plugin.json   # manifest
├── hooks/
│   ├── hooks.json               # SessionEnd → session-end.sh
│   └── session-end.sh           # fail-safe wrapper; calls capture.py
├── lib/
│   ├── common.py                # shared paths
│   ├── redact.py                # redaction + denylist (privacy gate)
│   ├── denylist.txt             # editable denylist
│   ├── capture.py               # transcript miner → failures.jsonl
│   └── doctor.py                # cluster + suggest
├── skills/doctor/SKILL.md       # /sandbox-audit:doctor
├── tests/                       # stdlib unittest + fixtures/
├── .github/workflows/ci.yml     # test + syntax check on push/PR
└── README.md
```

## Roadmap

- Real-time failure flagging (once event names are pinned to the installed version).
- Cross-session aggregator on a cron / `/schedule` routine producing a report.
- Gated auto-apply of `settings.json` diffs.

## License

MIT — Copyright 2026 Germán Andrés Delbianco Porta
