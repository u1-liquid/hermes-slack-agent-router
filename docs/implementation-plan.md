# Contextual Multi-Topic Routing Implementation Plan

Current implementation progress: source-grounded v2 people sets, semantic ingress/private
request projection, normal/busy/merge/runner-FIFO/replay, native admission/control checks,
streaming Jev caps/cancellation, shared immutable generations and operational CLI are coded.
Six real fictional journeys passed at the v2 question boundary; a fresh streaming client
canary passed separately. Retention/recovery CLI, purge tombstone/no rehydration, prior-rich
body, canonical duplicate call-count, oversized no-egress and pending-on-SDK-failure controls
passed. Full source collection: 76 tests, 73 passed and three explicit skips (two local external
canaries and the separate wheel job). The isolated rebuilt-wheel job passed separately;
offline Ruff and build passed. These are builder checks, not expanded independent acceptance.

> Use the selected sequential Roco/Sol-high native method with tests-first development and one consolidated independent Ritsuko review. Engineering choices are delegated; no repeated questionnaire or plan gate.

**Goal:** Real Jev contextual reference/topic decisions, one durable multi-unit plan, and only each recipient's assigned CURRENT instructions at the native input boundary.

**Spec:** [design.md](design.md), Astra/high delta plus fresh independent builder correction. Prior stable-main-only/no-classifier assumptions are superseded. Existing package/storage/native tests are compatible baseline evidence, not semantic acceptance.

**Architecture:** Original-request public Bolt middleware; positive human/native identity/control bridge; bounded allowed conversation snapshot; native `jev ask` closed-set questions; shared SQLite fenced plan; request-local `req.body` projection before listener/merge/busy/queue. Main remains trusted administrative fallback. No provider/transcript rewriting or new transport/broker.

## Engineering decisions
- Keep existing package/CLI/plugin identity and canonical shared database. Preserve original main/CAS/audit and old tests. Add semantic tables through explicit idempotent local administration (`init`/upgrade), never automatic destructive repair.
- `jev.py`: actual native CLI client, stdin `state`+Choice questions, strict typed answers and deadline/process cleanup; default executable `jev` resolves through normal PATH/config. Never embed credentials or use a fake response as real Jev execution.
- `semantic.py`: exact source candidates, typed question construction, validation and deterministic plan/projection. `plans.py`: common source/evidence-bound claim/lease/fence/result/unresolved store. Reuse existing Store permissions/normalization. Add modules only for these coherent responsibilities.
- Units use Unicode-code-point half-open spans in unchanged original authored text/field. Candidate boundaries account for every character (including punctuation/ack/reference); bounded same-line English/Japanese clauses supported. Mixed/unpartitionable/quoted/forwarded/media/size-limit cases are visible unresolved, never silently omitted or all-agent fan-out.
- One batch asks disposition, message/topic/person references and per-recipient membership, plus a whole-source coverage/mixed audit. Choices include explicit unknown. Locally validate exact answer keys/types, finite distribution/confidence, references, allowed recipient IDs, unit coverage and consistency before constructing the plan. No model-generated instruction text/IDs or owner transfers.
- Initial engineering ceilings: current text6000characters, history6messages, units6, recipients4, total typed questions96, semantic ingress budget2.5s and Jev sub-budget at most1.2s of remaining budget. Exceeding limits is unresolved. Conservative confidence0.8 is configurable evaluation policy, not calibrated truth. Tune only from permitted canaries, not private input.
- Config `semantic` is explicitly enabled with exact workspace/channel/data-policy declarations. Default egress disabled; SDK read access is not egress consent. Real runtime content permission is an operator deployment boundary, not implied by fictional tests or aliases. Only wholly fictional/public-permitted development calls.
- Source/context/registry/policy/main revisions and digests bind cache/plan. One claimant performs Jev, followers consume the same accepted plan with bounded waiting; crash takeover is fenced. No SQLite transaction across external work, no detached inference; timeout/invalid/stale/uncertain yields visible durable unresolved and empty ACK, not a generic-main success.
- Internal native projection uses a deep original snapshot and replaces `req.body` with a private event copy. Preserve IDs/auth context and only existing own source mentions in assigned units. Remove excluded CURRENT blocks/unfurls/files; nested edit fields also projected. Original and projected native gates both must permit, so removing another mention cannot widen admission. No fake mention/force-process/posting.
- Native history excludes current_ts and labels PRIOR context. Preserve accepted prefixes. Explicitly test current message in fetched history, rich duplicates and media uncertainty; do not build a general LLM firewall or rewrite history/tool pairs.

## Coherent tests-first batch
- [x] Write semantic protocol/plan tests RED before implementation: two topics/two recipients, context-only reply, mixed ack+action, same-topic multiple recipients, quote/forward, same-line English/Japanese clauses, unknown/mixed/incomplete coverage, invalid/stale/error/timeout.
- [x] Implement real client/validated plans and shared persistence; verify restart, two-process agreement/one accepted generation, cross-workspace, source/context changes, registry/main revisions, failed claimant/lease/fence and explicit unresolved inspection. Preserve main/audit and compatible baseline behavior.
- [x] Execute real fictional/public fixture(s) through the actual product Jev client. Preserve exact request/result/protocol/exit receipts privately; distinguish real canary from deterministic replay/unit fixtures. A prior recipient-choice canary or scalar code review does not satisfy this step.
- [x] Add actual native request projection tests RED: both recipients receive disjoint assigned action strings, references separately labeled, no current whole-message copy in blocks/history; no nonrecipient model/chat/warning. Inspect real native normal, active busy/steer, merged and queued/replayed input, not only labels.
- [x] Preserve commands, pending control owner and post-await recheck, bots/self/DM/monitoring/auth/native mention gates. Controls bypass Jev entirely. Verify original payload/provenance unchanged outside private request view and no implicit administrative main mutation.
- [x] Revise README/config/native acceptance to current semantic status, public-permitted input policy, retention/recovery/unresolved inspection and bounded limitations. Keep package/MIT/discovery/unload/isolated wheel and CI; required semantic tests cannot silently skip. Actual external Jev canary uses existing authentication only locally, not secrets in public CI.
- [x] Run relevant complete tests/lint/build, real local canary and isolated native/wheel checks; commit one coherent candidate with all remaining actual gaps explicit. No public push by builder.

## Independent review and publication
- [ ] Freeze candidate; independent Ritsuko maps CURRENT ten outcomes and actual Jev/native received text, exercises required checks, reports necessary corrections rather than editing. Jev code-quality review is separate from runtime Jev routing.
- [ ] Remediate confirmed in-scope defects as a batch, validate and independently bridge exact corrected source.
- [ ] Update the SAME authorized feature PR only after expanded local acceptance; no main/force push/merge. Read back exact source/tree/complete changed paths, PR and all declared exact-head CI. Preserve baseline receipts at their original boundary, not relabel old8criteria as current10acceptance.

## Safety and completion
No live Hermes/source/config/profile/skill changes, live plugin install, real Slack probes/private Jev input, Gateway restart, merge/auto-merge, release/PyPI or unrelated repositories. Official host remains source-pinned/read-only in an isolated checkout. Native finite12GiB members must preserve evidence and really return; no orphan children. Card remains running until the whole expanded product+independent review+same-PR/exact-head CI outcome is delivered. Shiori sends the single final requester report.
