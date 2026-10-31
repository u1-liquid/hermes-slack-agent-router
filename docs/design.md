# Contextual Slack thread assignment

Candidate implementation note: native semantic ingress/projection, source-derived people sets,
fenced retained generations and explicit metadata/retention/recovery CLI now exist locally.
Local operational/prior-rich regression, full source/native collection and isolated rebuilt-wheel
checks passed; this is not independent acceptance, hosted CI or live deployment. People are locally derived as the
set of authors of Jev-selected prior-message references, not a separate exclusive person Choice.
Known syntactic quote/code/forward units are nonaction references; relevant action/coverage
judgments retain confidence0.8. Purge/recovery require exact binding/fence, explicit dry-run/apply
and operator-asserted quiescence; main/audit are never deleted. See README for current limits.

Status: locally implemented and self-checked semantic candidate, awaiting expanded independent review. Supported native scoped-delivery boundaries are described in native-acceptance.md; this is not a live deployment or general classifier-accuracy guarantee. This replaces the earlier main-only/no-classifier design. Official source baseline: Hermes v0.22.5, `bf0203a794a07aac3ff764972ab9087baa4e4f4e`. Python, MIT, standard-library SQLite and minimal dependencies are engineering selections.

## 1. Observable contract

1. Jev resolves which bounded prior messages, people and topics a human reply addresses. Lexical mention matching alone is not contextual resolution.
2. One incoming message produces one shared plan containing all instruction units, references, topics and eligible recipient sets. Different units may have different recipients; same-topic multiple recipients are supported.
3. Each recipient receives only its assigned actionable source spans plus relevant, explicitly non-actionable reference material. The original message and provenance remain separate. Inviting several agents with the unchanged whole message is not sufficient.
4. An administrator-established thread main is a fallback for a generic continuation with no more specific grounded destination. A secondary invitation or topic decision never transfers main. An explicitly unresolved addressee is not a generic continuation.
5. Participants agree on the same durable per-message generation across processes/restarts, scoped by workspace, channel, thread and actual receiving bot/runtime. Stale evidence cannot silently reuse a plan.
6. Only trusted local administration establishes/transfers main. Participation, acknowledgements, quotes, classifier suggestions and unauthorized text do not. Existing threads support explicit bootstrap and recovery.
7. Preserve native authorization, channel admission, DMs/MPIMs, bot mentions-only/self-echo protection, monitoring, commands and pending approval/clarification/confirmation/update interactions. Routing never grants permission or wake eligibility.
8. A definite nonrecipient causes no agent turn, busy steering, queue entry or silence-warning substitute. Normal, busy, pending and queued paths require actual input-boundary verification, not just classifier-label tests.
9. Jev uses its actual typed interface with bounded latency and validated outputs. Timeout, invalid output, ambiguity and coverage gaps remain explicit unresolved outcomes; neither silent omission nor uncertainty fan-out is acceptable.
10. Development inputs are wholly fictional or public-permitted. Runtime contextual egress requires explicit input-policy authorization for the exact scope and data classes. Synthetic tests do not authorize private deployment; aliases/hashes/coarse features are not proof that private semantic content is safe to send.

Example journeys: a reply to an earlier diagram discussion reaches that discussion's eligible agent without transferring main; one message requesting a diagram check and a separate summary creates two assigned units; an acknowledgement followed by new work retains both classifications; an ambiguous “whoever promised this” remains unresolved rather than waking everyone.

## 2. Responsibilities and flow

The host owns transport, credentials, authorization, commands, pending controls, native sessions, queues and outbound delivery. The plugin owns evidence collection within permitted scope, one shared semantic plan, validation, recipient-specific views and local diagnostics. Jev supplies bounded semantic judgments, not authorization, ownership or arbitrary generated instructions. Local administration owns registry, main and recovery.

Flow:

1. At native ingress, resolve exact transport/runtime identity and exempt native controls before any classifier or text transformation. Unknown control ownership passes unchanged with degradation reporting; recheck pending state after awaits.
2. Preserve immutable original composition/provenance locally. Verify native authorization and the separate egress policy before fetching or sending semantic evidence. A bot token's ability to read a channel is not egress authorization.
3. Claim the canonical message generation in shared storage. One claimant builds a bounded evidence snapshot and one typed Jev question batch; other processes consume the same published result or a bounded unresolved result.
4. Validate full source coverage, references, recipients and evidence revisions. Commit the plan atomically using the claim's fencing token.
5. Build a recipient-specific internal view from exact assigned spans and selected references. Preserve envelope identity and native policy. Definite nonrecipients stop before core listeners.
6. Project all CURRENT composition surfaces before native enrichment/busy handling, preserving original provenance separately. Native history excludes the triggering current timestamp and labels prior messages as context. Verify this boundary without rewriting previously accepted conversation prefixes; section 6 records the fresh builder's correction.
7. Record planned, native-admitted and unresolved states separately. A plan is not proof of execution. Recovery is explicit and duplicate-aware, not a hidden replay queue.

Logical components follow these responsibilities: ingress/control bridge; evidence and span builder; typed Jev client/validator; transactional plan store; scoped-view projection; local administration. Reuse compatible existing gate/store behavior. No broker, general task orchestrator, dashboard or replacement Slack transport.

## 3. Evidence, units and actual Jev protocol

Use bounded actual prior messages with source message identifiers, sender identities/roles, authored text, quote/forward boundaries and prior validated topic/reference links. Start with the thread root, recent messages and directly referenced retained messages within explicit count/byte limits. Missing or truncated relevant evidence is recorded, never described as complete history. Use the exact workspace-bound existing SDK client for permitted read-only retrieval; do not borrow another participant's broader access. Shared evidence must lie within the permitted audience of every consuming recipient, or those recipients cannot share that snapshot.

A canonical source segment is `(message_key, content_revision, field_path, start, end, kind)`; offsets index the unchanged Unicode source using one documented convention. Preserve code/quote/forward/attachment distinctions. A unit contains `unit_id`, exact `source_spans`, disposition (`action`, `ack`, `reference`, `unresolved`), `topic_id`, referenced source/person IDs, recipient set, evidence and reason codes. A plan contains its immutable input/context/registry/policy/main revisions, generation, units, complete coverage accounting, unresolved reasons and per-recipient views. Topic IDs are local identifiers linked to source evidence, not model-invented authority.

Jev CLI compatibility input: version 0.23.1; `jev ask --timeout N` accepts stdin JSON with `state` and a named `questions` object and returns `answers`. A verified Choice question has `type: "choice"`, `instructions`, and a `criteria` mapping with at least two alternatives. Its answer includes `type`, `choice`, `probabilities` and `confidence`. `noul` yields probability; `score` operates on a list of at least two items. Do not invent freeform JSON-generation or multi-select response types. Use Choice for the initial implementation; do not require unverified additional type fields.

Construct deterministic candidate spans, then ONE batch of named questions about candidate action/reference status, relevant prior messages/people/topics and recipient membership. Multi-recipient routing uses separate closed-set yes/no/unknown membership judgments for each eligible recipient, not a single winner. Every question sees the same bounded source snapshot and candidate IDs. Include explicit unknown/no-fit alternatives. Assemble the structured plan locally; Jev does not generate its text or identifiers.

Candidate generation must cover every authored character with an accounted span, including acknowledgements and connective text. Sentence/line splitting alone is insufficient: punctuation, multilingual clause boundaries and same-line independent topics need finer candidate boundaries. Keep unsplittable or overlapping alternatives rather than silently dropping their text. Ask whether a candidate contains inseparable independent instructions; ambiguous segmentation becomes unresolved. Quoted/forwarded instructions remain reference data unless the authored request explicitly adopts a bounded part. Exhausting size/question limits produces an explicit unresolved reason, not truncation masquerading as successful classification.

Validate answer keys/types, finite probabilities, allowed criteria, confidence policy, exact source offsets, same-thread reference membership, complete coverage and registry-bound recipient sets. Contradictory membership/topic/reference answers invalidate the affected plan. Confidence is advisory, not calibrated truth or authorization. Exact threshold values and multilingual segmentation coverage require fictional/public evaluation; they are not established by the previous recipient canary. Choose atomic whole-message unresolved handling initially when any actionable unit cannot be safely partitioned, so successful units cannot conceal lost instructions.

## 4. Persistence, concurrency and administration

Thread key: `(workspace, channel, root_ts)` with opaque timestamps. Recipient key: `(workspace, receiving_bot_user, runtime_profile)` plus transport-profile provenance. Display names never identify authority. Ambiguous bot-to-runtime mapping is unresolved.

Use one operator-owned local SQLite database shared by participants on one host; profile-local default state is not shared consensus. Persist registry and main revisions/audits, bounded original/evidence snapshots, source revisions, topic/reference links, plan generations, leases/fencing tokens, recipient-view identity and unresolved/delivery receipts. This semantic design necessarily retains bounded content, unlike the former identifier-only design. Protect its directory, specify retention/deletion, and exclude transcripts from routine logs. Retain assignments independently of evidence expiry; expired evidence invalidates dependent recovery rather than erasing ownership.

A unique canonical message row coordinates `claimed → ready | unresolved`. Claim in a short transaction; release the transaction before SDK/Jev work. Publish only if the fencing token and captured revisions still match. Lease takeover after crash increments the fence; a late prior claimant cannot publish. A lease alone cannot guarantee exactly one remote request after a crash, but it can guarantee one accepted plan generation. Contenders must not independently classify on timeout.

Bind decisions to original composition digest, sender/thread/workspace, context snapshot digest, candidate schema, registry, input policy, main revision and classifier protocol/version. Equivalent message/app_mention deliveries may share a row only when composition/provenance equivalence is established. Edits have distinct content revisions. File notifications are not assumed equivalent to richer message events. An already delivered generation is immutable: later context or transfer applies to new input; any explicit recovery uses a linked new generation and prevents duplicate delivery. A stale undelivered generation becomes unresolved/recomputed under a new fenced claim, never conflicting cached allows.

Terminal-only administration retains `status/check`, `show`, `establish --if-absent`, `transfer/clear --expected-revision` and auditable reasons. Add plan inspection, unresolved listing and explicit recovery with input/revision/delivery checks. Do not expose main mutation as a model tool or infer it from Slack text. Bootstrap registry/main and declare an evidence cutoff for existing threads. Recovery does not bypass native wake or authorization, does not invent a new Slack message, and must not claim automatic replay where the host provides no verified replay contract.

## 5. Timing, uncertainty and privacy

Use a single monotonic end-to-end ingress budget accounting for SDK/context, database contention, Jev process startup/request and final acknowledgement overhead. The documented Jev timeout is a sub-budget, not the transport budget. Set a conservative configurable ceiling below the measured installed Socket Mode/Bolt acknowledgement deadline; the exact safe value requires an SDK integration measurement. Do not reuse the host's retrying history helper inside this budget without an outer timeout: it contains rate-limit sleeps. Run blocking database/CLI work off the event loop, cancel and reap request-scoped subprocesses, and never leave inference running after its caller abandons a claim.

On a known ordinary eligible input, timeout, invalid answers, privacy refusal, stale evidence, ambiguous partition or missing main yields a durable unresolved record and empty transport acknowledgement without inference. If storage itself is unavailable, emit a bounded local diagnostic and no claim that recovery is durable. The initial unresolved policy favors no accidental execution over availability; it must be visible in operator status, not a silent discarded instruction. No per-message generic approval gate is introduced. Native controls and unknown control mapping are different: preserve their native handling and label degraded routing coverage.

A main fallback is valid only for a safely established generic continuation, not as a universal substitute for failed multi-topic analysis. Diagnostic recovery must distinguish `generic-main`, `semantic-resolved`, `privacy-disabled`, `classifier-failed`, `coverage-gap` and `native-projection-unverified`.

Default semantic egress is disabled until exact workspace/channel and data-class policy is configured. Public channel names alone do not prove public content; credentials/customer/private material remain excluded. Development never uses private content or reversible private derivatives. Existing authentication is used without copying credentials. Runtime authorization for a different data class is a deployment decision, not a consequence of passing fictional canaries.

## 6. Native integration: established seams and the remaining delivery check

### Early ingress

Use `ctx.register_platform_handler("slack", factory)` and public Bolt `native.use(async_middleware)`. Global middleware precedes listener dispatch even though the pinned adapter calls factories after registering core listeners. Pass through with `await next()` once; definite nonrecipients return `BoltResponse(status=200, body="")` without `next`, `say` or `respond`. Do not install a competing message listener or patch host methods.

The proposed scoped view is an INTERNAL request-local copy, not a posted Slack event. Preserve workspace, channel, sender, timestamp, thread, event identity and original provenance. Replace only the model-facing composition with assigned spans/references; remove unassigned block/unfurl/file composition from that view. Do not add mentions or `_hermes_force_process`. Preserve original native admission evidence separately: narrowing text must neither manufacture wake eligibility nor accidentally erase a genuine original mention required by native admission. Whether the SDK permits a request-local event/body substitution that satisfies both conditions is an explicit builder check, not a claimed tested fact.

Commands, pending controls, DMs/MPIMs, bots, self-echoes and monitoring bypass semantic transformation. Use the existing exact native identity/session resolver and read-only pending-state bridge; recheck after awaits. No atomic pending-state lease is exposed. Do not exempt ordinary traffic merely because the session is busy.

For `file_shared`, the core constructs an empty-text synthetic event and calls its handler directly, without a second Bolt traversal. Intercept the original notification. Exact workspace/channel/share/sender metadata is required; `_first_file_share` can fall back to another channel and that fallback must not be accepted. Metadata-only classification cannot understand attachment contents. File semantics or inseparable attachment scope remain unresolved unless a separately permitted bounded representation is available. No extra downloads or replacement transport are selected.

### Selected projection and history boundary (fresh builder correction)

The actual formatter (`adapter.py:5902–5904`) excludes the triggering `current_ts`; `5926–5935` labels the rest as PRIOR thread context. `_hydrate_thread_context:4339–4348` changes only the new turn, not accepted history. Prior references are not a second active copy of CURRENT instructions. General provider-request filtering, transcript surgery, nonce markers, tool-pair rewriting and a session-reset prerequisite are therefore not selected. This corrects an engineering hypothesis, not a requester waiver or a claim of a general prompt-injection firewall.

Use public Bolt middleware's `req` argument. Preserve a deep original snapshot, construct a request-local body/event copy and assign `req.body` to it before `await next()`. Downstream kwargs injection reads that body at listener invocation. Rebinding a local `body` variable does not project downstream; mutating a caller-owned payload or restoring the body while async listeners run is incorrect. Keep native envelope identity/auth context, and project nested edited composition as well as flat text. Do not modify raw signatures or post another Slack message.

Replace CURRENT actionable composition with exact assigned spans and labeled selected references. Remove excluded rich blocks, attachments/unfurls and current files; unsupported or inseparable current/root media yields explicit atomic unresolved, never silent action deletion. Relevant bounded prior references remain non-actionable context. Test cold/mention/restart hydration with a source history containing the triggering original message to prove its exclusion.

Preserve an own mention only when the human authored it in the SAME assigned unit. Never manufacture mentions or force-process flags. Admission is the intersection of ORIGINAL and projected native policy: stripping another user's mention must not remove an original native denial. Context-only assignment relies on existing native thread wake/free-channel rules; routing is not authorization or forced delivery. Check the existing channel gate monotonically without running side-effectful wake routines twice.

The projected event is constructed before BasePlatformAdapter chooses normal, merge or busy paths; queued/replayed payloads retain that committed scope and must not expand back to the original whole message. Pending controls bypass projection and are rechecked after awaits. Actual native tests must inspect received/steered/queued text and prove no unassigned CURRENT action, not merely read a recipient label. No new provider middleware is required absent a concrete counterexample at this boundary.

### Lifecycle and failure limits

Native factory dedupe and lack of physical callback unwiring require a plugin-owned disposed flag; retained closures pass through after unload. Replacement/re-enable may require restart. Report incomplete activation instead of success. Host hook/request-middleware exceptions fall through; throwing is not fail-closed enforcement. Health checks must distinguish active ingress gating, semantic service, shared-store identity and verified projection capability. Disabled/broken plugins, unknown identity/control paths and already admitted work are not covered by an unconditional enforcement guarantee.

## 7. Alternatives and required evidence

Main-only routing is a preserved fallback, not the current product. Prompt-only instructions and waking all recipients with unchanged CURRENT input fail scoped execution. Independent per-agent Jev calls fail shared agreement. Pre-dispatch-only rewriting misses legacy busy and retains enriched CURRENT fields. Early global middleware with a private request-body projection is selected after the fresh builder source check. Preserve native PRIOR context and accepted prefixes rather than inventing provider-request filtering or transcript surgery. A new broker or core monkeypatch is rejected.

Before acceptance, exercise actual typed Jev requests with fictional/public inputs, then inspect actual recipient input at native and provider boundaries: two topics/two recipients, contextual unmentioned reply, same-topic multi-recipient work, mixed acknowledgement/action, same-line multilingual clauses, quotes/forwards, missing evidence, invalid/timeout/abstain, retries/edits, stale registry/context, cross-workspace collisions, two-process lease takeover, restart and transfer preservation. Include normal/legacy busy/shared busy/queue/replay/merged media, pending controls and native denial. Assert no model/warning for nonrecipients and no unassigned actionable content for recipients. Cover cold/mention/restart hydration, root images, tool loops and compression. Keep packaging/CI/lifecycle checks; old main-only results do not establish the expanded outcomes.

## Sources

All source paths below refer to the [official pinned revision](https://github.com/NousResearch/hermes-agent/tree/bf0203a794a07aac3ff764972ab9087baa4e4f4e). They establish available contracts and identified ordering, not execution acceptance.

- `plugins/platforms/slack/adapter.py:1618–1702`: native listener/factory ordering.
- `plugins/platforms/slack/adapter.py:3992–4057`: file-share helper and direct synthetic fallback.
- `plugins/platforms/slack/adapter.py:4335–4398`: cold, mention and restart hydration plus root media.
- `plugins/platforms/slack/adapter.py:4580–4693, 4695–4743`: enrichment, native auth/mention admission, media, event construction and dispatch.
- `plugins/platforms/slack/adapter.py:5800–5855, 5870–5885, 5888–5936`: SDK history, retry delays and rendered context.
- `gateway/platforms/base.py:3989–4108`: burst, active-session and control selection.
- `gateway/run_busy.py:887–958`: authorization, approvals, steering and queue handling.
- `gateway/run_inbound_hooks.py:65–112`: pre-dispatch text-only replacement and exception fall-through.
- `website/docs/developer-guide/plugins/index.md:1650–1686`; `hermes_cli/middleware.py:88–99`: supported effective provider-request replacement and failure behavior.
- `agent/turn_api_request.py:143–147`: request middleware call with session/task/turn/request context.

Public references: [Hermes plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins), [Hermes hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks), [Bolt global middleware](https://docs.slack.dev/tools/bolt-python/concepts/global-middleware/). Jev protocol facts above are bound to CLI 0.23.1 help and executed fictional product-client requests. Local multi-unit journeys and supported native projection checks passed; broad semantic accuracy and live deployment remain unqualified.
