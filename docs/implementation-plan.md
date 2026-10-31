# Slack Thread Assignee Implementation Plan

> **For agentic workers:** Use the already-selected native finite Roco/Sol-high execution method and TDD. Independent Ritsuko review follows the coherent implementation, not every test. The accepted packet delegates engineering decisions; no repeated user plan gate.

**Goal:** Persist a stable main for Slack human thread continuations while preserving message-local explicit secondary/multiple recipients and native controls.

**Architecture:** Original-request Bolt global middleware via official native factory; a pinned read-only Hermes identity/pending bridge; shared local SQLite with atomic decisions and CAS administrative mutation. Core transport/listeners/auth remain untouched.

**Tech stack:** Python >=3.11, standard-library policy/storage/admin; host-provided Slack Bolt/PyYAML at integration, pytest/ruff/build for development. No remote classifier.

**Spec:** [design.md](design.md), independently produced Astra/high and corrected following fresh builder contract check.

## Decisions and scope
- Public package `hermes_slack_thread_assignee`; plugin ID `slack-thread-assignee`; console command `hermes-thread-assignee`, also host CLI `hermes thread-assignee`.
- Files: `policy.py` (direct address parsing and eligibility), `store.py` (SQLite/CAS/event snapshot), `config.py` (validated explicit shared DB + participant registry/exemptions), `bridge.py` (pinned native receiver/runtime/pending normalization), `plugin.py` (native middleware/factory/unload), `cli.py` (trusted OS admin). Split only if responsibilities justify it.
- Native factory signatures/CLI hooks follow actual official API, not guessed signatures. No importing unrelated plugin implementations.
- Explicit operator config file path via `HERMES_THREAD_ASSIGNEE_CONFIG` for both CLI and plugin; use fictional example only. All participants use one DB and registry. Store initialization explicit through admin; startup never repairs corruption.
- `init`, `status`, `check`, `show`, `establish`, `transfer`, `clear` provide machine-readable output; mutations support dry-run; establish insert-only, transfer/clear CAS. Local administrator OS trust, not Slack/LLM text.
- Thread `(workspace,channel,root)` and recipient `(workspace,bot_user,runtime_profile)`; event keys distinguish edits and file fallback provenance. Persistent tombstone revision prevents ABA after clear.
- Corrected design's exact early-file metadata checks and pending recheck are required. No blanket busy bypass, guessed first bot/profile, quote/unfurl routing or ignored-channel grant.
- No private paths/IDs/logs/evidence in public repo. MIT u1-liquid. No public claim of universal/fail-closed gating; list actual framework race/lifecycle limits.

## Review focus
1. Native routed runtime identity/pending key mismatch: preserve controls, surface degradation, never guess.
2. Retry/edit/file paths with differing address evidence: no cached wrong recipient, no ownership changes.
3. Shared processes/admin races: stable decision snapshots, CAS/tombstones, safe corrupt/locked state.
4. Original mixed busy bursts and video fallback: rejected input never reaches model/steer/queue/chat.
5. Unload/re-enable: retained native closure becomes pass-through; restart requirement explicit.

## Coherent implementation batch
- [x] Write meaningful policy/store tests first, execute RED before implementation. Detect stable main, secondary then main, multi-address, quote/code, unknown, collision, restart, CAS/concurrency, evidence mismatch, lock/corruption.
- [x] Implement minimal policy/config/store/admin and run focused GREEN. Record actual failures/passes in private result, not public logs.
- [x] Write early native gate tests RED; implement official factory/middleware and pinned bridge; test actual AsyncApp dispatch and native Hermes methods in an isolated copy/environment. External I/O only is mocked; no live APIs, profiles or source writes.
- [ ] Exercise normal, busy/steer/queue, mixed burst, pending controls, commands, bot/self/DM/monitoring, routed profile and file fallback with model/steer/queue/outbound counters. Verify empty 200 transport ack separately. Include callback fail-through honestly.
- [x] Add manifest/entry point, unload handling, MIT, fictional config, README install/uninstall/bootstrap/limitations, and CI for Python 3.11–3.14 tests + lint/build + pinned official-host integration.
- [x] Build wheel/sdist, discover/register through isolated target/home, execute checks and record exact revisions. No live installation.
- [x] Commit coherent candidate on feature branch; return self-check and uncovered criteria. No push/publication by builder.

## Independent review and publication (owner)
- [ ] Freeze exact candidate; independent Ritsuko/Sol-high executes required acceptance checks and reports defects, not shipping edits. Return necessary fixes to same writer, retain good evidence.
- [ ] Apply current Jev code review policy after relevant checks; it does not replace independent review.
- [ ] Verify hosted repo/public nonfork/main, exact complete changed paths and sanitized contents. Publish ordinary feature branch/PR, read back exact target/head/base; no main/force push or merge.
- [ ] Execute declared exact-head CI, read all job/check results including required checks, record private criterion matrix and resources. README must reference existing feature branch while unmerged.

## Verification boundary
Native integration uses official Hermes revision `bf0203a794a07aac3ff764972ab9087baa4e4f4e` in an isolated checkout outside any Hermes home. SDK/host source revisions and mocks must be reported. Host-owned queued/replay work, permission refusal, pending/metadata races and no-unwire lifecycle are disclosed limitations, not fabricated enforcement. Initial packet remains the whole-product acceptance contract.
