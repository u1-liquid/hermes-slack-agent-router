# Stable Slack thread assignment

Status: source-grounded architecture selected for implementation, not executed integration acceptance. Baseline: official Hermes v0.22.5, revision `bf0203a794a07aac3ff764972ab9087baa4e4f4e`. The supported registration route is a native platform factory plus Bolt global middleware; the local identity/control bridge remains version-specific. Python, MIT and minimal dependencies are engineering selections.

## User contract

A channel thread has zero or one durable main recipient. An ordinary human continuation without a direct agent address is eligible only for that main. A direct secondary mention invites that recipient for this message, not subsequent messages. Multiple direct agent mentions invite all named recipients. A main not mentioned in an explicitly addressed message gains no additional eligibility from ownership alone.

Only trusted local administration establishes or transfers main. Participation, incidental mentions, agent acknowledgements, quoted content and unauthorized senders never change it. Threads are independent; restarts preserve assignment. Transfer governs subsequent decisions, not accepted work or conversation history.

Eligibility narrows host permissions; it never grants access, forwards to another bot, impersonates a user or forces a wake. DMs/MPIMs, bot-origin traffic, native commands, pending approval/clarification replies and configured monitoring retain native handling. Rejected ordinary continuations cause no model turn, busy steering, queue entry or substitute warning. Ordinary busy/media messages are required coverage, not exemptions. This is not a security boundary against a disabled or broken plugin.

## Responsibilities and flow

1. The host owns Slack transport, authentication, channel policy, bot/self-echo protection, commands, pending interactions, merge/queue behavior and delivery.
2. The plugin receives each original native request before listeners. It checks scope/exemptions, obtains exact receiver/runtime/thread identity through a read-only host bridge and extracts direct recipient evidence.
3. For `file_shared`, it resolves only the metadata needed to classify the native video fallback before that fallback is invoked. No download, body rewrite or replacement handler is involved.
4. The policy reads the shared assignment and atomically captures an event decision. Every participating recipient checks the same decision evidence. No incoming message changes ownership.
5. Eligible/exempt/uncertain inputs continue unchanged through the native chain. Definite non-recipients receive only an empty transport acknowledgement; core listeners do not run for that request.
6. A local administration interface provides bootstrap, explicit transfer, diagnostics and recovery.

Implement a pure policy, a small transactional store, a source-pinned host bridge and registration/admin glue. Do not build a generic router, duplicate Slack transport, use an LLM classifier or add a broker.

## Identity, storage and concurrency

Thread key: `(workspace_id, channel_id, root_message_ts)`. Timestamps are validated opaque strings, never floats. A top-level message can identify a future root but never automatically establishes main.

Recipient identity: `(workspace_id, receiving_bot_user_id, runtime_profile_id)`, with transport-profile provenance retained for validation. A profile alone is not a bot. An exact participant registry maps identities, never display names. A mention mapping to several possible runtime profiles is ambiguous, not permission to choose one. Missing workspace/receiver must never fall back to the first bot or process-global profile.

Use standard-library SQLite in one explicitly configured operator-owned local database shared by all participants. Default Hermes plugin state is profile-scoped and insufficient for this purpose. No state in the install tree or another profile's home. Require a common database identity and registry revision. Supported scope is one host/local filesystem, not network-filesystem SQLite or cross-host consensus.

Persist participants/schema revision; assignment/main revision; atomic old/new administrative audit; and event decisions. Store only necessary identifiers, revisions, direct-recipient IDs/evidence kind and dispositions, never transcripts, attachments or secrets.

Use short transactions, bounded lock waits, unique keys and compare-and-swap. Establish is insert-if-absent; transfer/clear requires the observed revision. Audit and mutation commit together. The first decision atomically captures assignment so a concurrent transfer cannot make recipients use different mains for the same input. This is eligibility agreement, not exactly-once delivery.

A decision snapshot must bind the SAME registry revision, policy revision, canonical input identity, sender/thread scope and direct-recipient evidence. Compatible `message`/`app_mention` duplicates share a decision; edits have distinct identities. Evidence mismatch must never reuse a cached allow/drop silently: diagnose and preserve native handling. Do not make policy/registry revision a way to create competing decisions for one input. A `file_shared` fallback has distinct provenance and empty composition by the native contract; do not conflate it with a richer normal message unless equivalent evidence is proven. Native dedup remains native. Retain decisions through the declared retry horizon; older retries have no consistency guarantee. Never expire assignments or replace corrupt state silently.

## Bootstrap and local administration

Register terminal-only `hermes thread-assignee` through `ctx.register_cli_command`; do not expose assignment mutations as model tools or Slack slash commands.

- `status` / `check`: database/registry identity, schema, native middleware activation, supported version/topology, integrity and degradation reasons.
- `show --workspace … --channel … --thread …`: main and revision.
- `establish … --recipient … --if-absent`: new or existing thread.
- `transfer … --recipient … --expected-revision … --reason …`: explicit reassignment.
- `clear … --expected-revision … --reason …`: unknown, not automatic election.

Provide dry-run and exact-key/old-new/revision receipts. Trust is the local OS account and protected database/directory permissions, not protection from another program under the same account. Schema migration is explicit with consistent backup; startup never resets unreadable state.

Bootstrap registers participants and explicitly establishes main. Verify the target's native admission rules; if needed, a human mentions it once to establish native wake history, not ownership evidence. Transfers cannot override denied channels or strict mention requirements. No historical-message scraping is needed.

## Selected integration: native global middleware

Register one factory with `ctx.register_platform_handler("slack", wire)`. It receives the existing Bolt `AsyncApp` and read-only adapter. Call public `native.use(async_middleware)`; do not add a competing `native.event("message")` listener or modify listener/middleware tables.

Important documentation correction: this pinned Slack adapter registers core listeners and its catch-all BEFORE invoking plugin factories (`adapter.py:1618–1702`), despite general Hermes documentation describing before-core factories. Bolt GLOBAL middleware still runs before listeners regardless of that registration position. This is the supported earlier boundary that solves the previous pre-dispatch-only design's legacy-busy and merged-burst gaps.

For pass-through, call and return `await next()` exactly once. For a confident rejection, return `BoltResponse(status=200, body="")` without calling `next`. This is transport acknowledgement, not `say`, `respond` or a chat message. Returning no response without calling next is not a correct silent rejection. Do not catch downstream failures and call next a second time; exception handling is limited to plugin classification/storage work before delegation.

Scope behavior to Events API `message`, `app_mention` and the video `file_shared` fallback. Other requests, actions, views, slash commands, lifecycle/reaction traffic and native control flows pass unchanged. Pure-copy normalization of edits may be used for classification; never mutate the incoming request/body. Detect commands including recognized `!` aliases and commands behind this bot's mention. Any conservative overbroad command pass-through must be reported as degraded coverage, not complete routing.

Each ordinary message is gated before Slack hydration, base-adapter busy selection, steering and text/photo merging. This applies to both shared-authority and legacy busy paths; do NOT exempt an active session merely because it is busy. Only already-eligible inputs may merge downstream. `pre_gateway_dispatch` and `post_gateway_admission` are not the primary gate and are not required as a substitute second dispatcher.

### Exact read-only identity/control bridge

Use verified envelope workspace and this adapter's workspace-specific bot/client maps, never a first-token fallback. Build a minimal temporary source through native `build_source`, canonicalize that temporary source through the host resolver, then read its `RoutingIdentity`. This uses the native route algorithm rather than reproducing `profile_routes`. Do not modify adapter/core state or dispatch the temporary source.

Resolve the exact native session key and runtime/transport scopes. Before any rejection inspect the SAME host pending clarify (including choice prompts), slash-confirm, blocking approval and update-prompt state. Pending input passes unchanged. Failed/mismatching key or scope inspection passes with a local diagnostic. Recheck after awaited metadata/storage work immediately before rejection. No atomic pending-state lease is exposed; a control-state race remains a compatibility limitation, not an excuse to bypass all busy traffic.

Classify from original direct composition: native mention elements or flat `<@…>` tokens outside quoted/code/preformatted/forwarded/unfurl content. Never parse rendered/humanized text or thread history. Preserve native API-human overrides and bot/self policy. Missing bot markers or `is_bot=False` alone do not prove a human; unknown sender category passes with degraded coverage. Monitoring exemptions use exact configured workspace/channel/sender rules or trusted provenance, not text keywords.

These private read-only helpers/maps are source-pinned dependencies, not a universal public normalized-message API. Support only tested host/SDK versions and topology; surface unresolved bindings instead of guessing.

### Early `file_shared` metadata classification

The core's video-only fallback (`adapter.py:4008–4057`) fetches `files.info`, selects share metadata, synthesizes an empty-text `file_share` message and directly calls `_handle_slack_message`; that synthetic call does not traverse Bolt again. Therefore the global middleware must gate the ORIGINAL `file_shared` notification, not wait for a second message middleware invocation.

For an otherwise in-scope notification:

1. Require exact workspace, channel and file identifier. Preserve DM/MPIM, ignored/exempt and known bot/control traffic first where identifiable; incomplete conversation type or control mapping is uncertainty, not channel proof.
2. Use only that workspace's already authenticated SDK client for a bounded `files_info(file=…)` metadata query. No first-client fallback, extra credentials, classifier, content download or file export. Failure, timeout, missing scopes, malformed data or non-video content passes to native handling with an appropriate local diagnostic (non-video is simply outside this fallback).
3. Require an unambiguous exact-channel share and valid share timestamp/thread relationship. The native `_first_file_share(file_obj, channel_id)` is reusable read-only, BUT it falls back to the first share ANYWHERE when the requested channel is absent (`3992–4006`). Validate exact-channel membership and ambiguity before accepting its output. Never adopt that fallback. Multiple unresolved shares, absent exact share timestamp or contradictory sender/thread evidence means pass-through; `event_ts` is not proof of a missing share/root.
4. Construct only a temporary classification message matching core fallback semantics: empty direct composition, exact channel/workspace, sender from `event.user_id` or file metadata with conflicts treated conservatively, and the verified share/thread identity. Keep the real share timestamp for decision identity; do not copy the core's deliberately blank synthetic `ts` into a guessed identity. An absent thread on a top-level share does not establish a main.
5. Apply native source/runtime/pending resolution and ordinary recipient policy. Reject with empty 200 only when all evidence is sufficient; otherwise continue the original request unchanged. Core alone performs its delay/dedup/download/handler dispatch.

This duplicates only eligibility metadata resolution, not transport. On admitted notifications the core may query metadata again. A change between those reads is not atomically controlled by the extension; test and disclose this race. No claim of immutable share metadata or identical cross-path dedup is made. Test file-only video and normal-message/file-notification ordering, including explicit mentions in the richer normal message. Do not collapse their differing recipient evidence into one cached decision.

### Fault behavior and lifecycle

Normal handled outcomes:

- Known ordinary input with unknown main, or bounded store lock/read/corruption failure: silent empty-200 rejection and local diagnostic; no election, reset or model fallback.
- Explicit addresses with complete evidence: evaluate the addressed set, without changing main. Failure to establish consistent shared decision evidence must not become an invented allow.
- Missing/ambiguous identity, sender, direct evidence, file metadata or pending inspection: native pass-through plus a bounded degradation diagnostic. This intentionally preserves safety/control, but is degraded ordinary coverage, not an exemption or full enforcement.
- Plugin-local unexpected exception before delegation: catch, record locally and pass through once; never swallow downstream errors or retry delegation. Do not claim unconditional fail-closed behavior.

Use bounded metadata calls and off-loop local database work within the transport acknowledgement budget. Do not add a separate acknowledgement transport, sleeping loop or background queue. Runtime metadata lookup is normal existing Slack SDK use, not third-party classification.

The factory is deduped per native app by plugin/factory identity. The host does not un-wire native callbacks on disable. Register `ctx.on_unload` to set a plugin-owned disposed flag; retained middleware immediately becomes pass-through, with safe in-flight resource release. Do not edit Bolt lists or host dedupe registries. Replacement/re-enable of the same factory requires gateway restart to obtain a new native client/closure; report restart-required, not successful hot replacement. Late initial activation can affect future requests, never already accepted/queued work. Reconnect must bind the new adapter/client identity without retaining stale workspace maps.

Unavoidable current extension limits: no atomic pending-state lease; no atomic file-metadata/classify/admit transaction; no physical native callback un-wire; registration failure/disabled plugin/earlier middleware can prevent this policy running; committed input is not retroactively gated; private bridge compatibility is not version-independent. Native auth/channel/strict-mention refusal is retained and cannot be overridden. None of these means ordinary legacy busy or mixed bursts should be excluded: those are addressed by early middleware and must be tested.

## Alternatives and release evidence

Prompt/output filtering is rejected because inference/side effects already occur. Pre-dispatch-only gating misses legacy busy and sees some inputs after merging; post-admission lacks original recipient evidence and is after busy steering. A competing Slack event listener is behind core's first match. Global middleware is selected because it uses the existing official factory/SDK and preserves all core listeners. A future normalized host gate could remove private bridge dependencies; no live-core patch is proposed.

Before release, exercise actual AsyncApp dispatch and Socket Mode acknowledgement in an isolated official host environment with synthetic fixtures. Bind the supported Bolt version; current SDK documentation is API evidence, not an installed-version test. Required cases:

- Stable main, secondary then main, multi-mentions, per-thread ownership, quoted/code mentions, unauthorized ownership text.
- Workspace collisions, multiple bots, routed profiles, ambiguous identities, DMs/MPIMs, bots/self/API-human, monitoring, commands behind mentions and `!` aliases.
- Normal, legacy busy steer/queue, shared busy, mixed text/photo bursts and file_shared-only video, including exact-share ambiguity, missing metadata, timeout and both normal-message/file-notification arrival orders. Assert no model/steer/queue/outbound chat on rejection.
- Pending clarify/approval/confirm/update and races; native auth denial; accepted FIFO replay unaffected by transfer; direct-evidence mismatch and edit/retry behavior.
- Two-process agreement, restart reopening, transfer CAS, registry/policy mismatch, bounded lock/corruption handling; no destructive automatic recovery.
- Registration failure, late initial load, unload pass-through, restart-required re-enable/replacement and reconnect. Verify response status/ack, not only callback return values.
- Isolated discovery/Plugin Doctor, packaging and CI; no live Slack probe, live install or gateway restart needed for development acceptance.

## References

Official Hermes [plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins) and [hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks); Slack [global middleware](https://docs.slack.dev/tools/bolt-python/concepts/global-middleware/) and [AsyncApp API](https://docs.slack.dev/tools/bolt-python/reference/async_app.html).

Paths at the [pinned official Hermes revision](https://github.com/NousResearch/hermes-agent/tree/bf0203a794a07aac3ff764972ab9087baa4e4f4e):

- `plugins/platforms/slack/adapter.py:1618–1702, 1756–1778, 1824–1834`: actual listener/factory ordering and authenticated workspace maps.
- `plugins/platforms/slack/adapter.py:3992–4057`: share helper's cross-channel fallback and file-only video path.
- `gateway/platforms/base.py:2258–2298, 2405–2427, 2507–2517, 4782–4824`: factory dedupe and native identity/session seams.
- `gateway/session_identity.py:42–92`; `gateway/run_adapters.py:1710–1802`: transport/runtime distinction and profile scope.
- `gateway/platforms/base.py:1742–1788, 3989–4156`; `gateway/session_ingress_burst.py:77–103`; `gateway/run_busy.py:887–958`: merge/busy paths behind the selected gate.
- `gateway/run_inbound.py:246–269, 1130–1144, 1203–1284`; `gateway/run_inbound_consumer.py:1–58`: pending and later hook ordering.
- `plugins/platforms/slack/adapter.py:2865–2900, 4098–4142, 4186–4225, 4449–4473, 4536–4576, 4695–4743`: sender rules, native admission and transformed mentions.
- `website/docs/developer-guide/plugins/index.md:1994–2040, 2088–2098`: factory API and no-unwire lifecycle; general before-core wording is superseded by actual pinned Slack ordering above.
