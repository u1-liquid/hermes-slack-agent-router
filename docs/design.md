# Hermes Slack Agent Router — runtime design

## Shared ordered routing contract

The current yes05-joint-v1 keeps this structure with the accepted J rule7 correction:
a correctly addressed eligible bot may participate despite human/context-only/outside
co-assignees, preserving complete own joint meaning without invoking outsiders or
claiming their receipt/consent/execution. Main cardinality and native self-auth,
identity ambiguity and independent foreign-source boundaries are unchanged. The
primary selected YES requires native confidence>.5; exactly.500 rejects/.501 admits.
NO never admits; probabilities and scope confidence cannot rescue admission.
Classify FN/extra triggers as classifier observations, separately from hard native
authorization/source/format/isolation failures. Historical thresholds/vetoes below
remain historical evidence where explicitly labelled prior.

Both response and conditional scope serialize the identical full ordered nine-rule
routing_contract. Their instructions contain exactly question, evidence,
routing_contract and worked_contrasts, in that order. Existing question/evidence
strings remain exact; only accepted J explanation/criteria and the self-contained
example people member prospectively amend the original shared-contract version.
This is the adopted shared-contract consistency correction,
not evidence of semantic qualification. State, extents, priors and native gates do
not change. The existing frozen campaign evaluates all167 recovery-stage rows with
fresh requests, never old-answer replay as evidence against changed instructions.

## Readable-rubric-v2 clarification boundary

The original source layout, protocol, identity facts, candidate catalogue and consumer gates
are retained. A redundant `current_author_content` view is literal unquoted CURRENT
concatenation in source order, without normalization or inserted separators, plus
exact quoted/reference paths. It is not a task, recipient or response decision;
nonempty unquoted text alone is not a request. Full original text/segments remain
authoritative for source copying and whole-conversation interpretation.
Current conditions distinguish a fresh explicit address
from an independent-topic destination inferred only from historical ownership.
Only the former carries coordinated clauses; same-request rejection/support remains
whole. Positively appointed main/co-leads differ from unsettled rival claims, and
only collisions among supplied names require evidence for the actual task. An
unambiguous conversational name/short given form needs no prior task/main ownership;
no alias or local name router is invented. Under the amended plain-name-main-v1
policy, a bare no-@ name call/general continuation without independently specific
topic allocation, assignment or genuine handoff remains with evidenced main, even
if another plain name occurs. That name alone is not mandatory activation or a main
handoff. This neither invents unknown main nor makes main veto another topic owner,
all no-@ main, reply-all or an authorization change. Exact <@USER_ID> syntax
identifies native users without inventing unknown names/kind, but token presence
alone does not address a subject, example or quote. Catalogue quoted/reference
status constrains whole-message interpretation as well as source copying.

The test-only full-view-native-v2 assertion independently specifies exact own
CURRENT plus actually validated inert references before formatting the complete
view. It compares whole native text, sender input and metadata; formatting CURRENT
alone is not an interchangeable oracle for a prefix of a reference-appended view.
No Plan.view/native adapter trim or production presentation change follows.
Raw policy labels remain diagnostic; negative silence has no extra correct-label
or confidence gate. Old failures remain failed historical evidence. Full mandatory
103 retained/24 H regression/24 F fresh/12 private-real qualification and independent
acceptance precede any adoption; no automatic alternate candidate or rollout.

## Native-derived participation

`register(ctx)` supplies a Slack platform-handler factory. The factory installs
Bolt middleware without reading a plugin configuration or requiring a socket to
be ready. Participation is derived at request time, not registration time.

`Bridge.bind` resolves the current workspace, channel, human sender, receiving
bot, canonical routed runtime and native session key. Native commands, DMs/MPIMs,
bots/self and pending controls retain their native path. Definitive sender denial
precedes semantic history and inference.

`Bridge.participants` reads the runner's primary and profile adapter maps. It does
not enumerate profile directories or use the shared-bot fallback to manufacture
extra transports. Same-workspace `auth.test` identity/client mappings, live socket
state, native admission and session authorities establish eligible candidates.
Each adapter builds a fresh source for the actual sender/channel/thread and uses
the host canonicalizer. Transport ownership and runtime name/home must agree with
served, non-retiring authorities. Two distinct bots may route to the same runtime;
two transports claiming the same workspace/bot are ambiguous.

The experimental human-name correction binds request-local presentation labels to
those already eligible workspace/user identities. It reuses each native adapter's
`_team_bot_names`; display/real-name lookup on BOTH warm and cold paths
uses that adapter's existing workspace client and validates `ok`, exact user
ID, exact team ID and bot status. At most four parallel `users.info` lookups run
alongside unchanged history fetching without a plugin elapsed-time cutoff.
No plugin cache or native cache write
is introduced. Missing/invalid labels cannot create recipients. Labels are untrusted
semantic data, not instructions, permissions or authority; duplicate names alone
cannot prove a unique current recipient. Opaque cached handles do not establish
full native labels. Existing account-scoped handles alone remain the fallback on
lookup failure; no name is fabricated and no structured given-name field is assumed.
Topology witnesses include native label values. Semantic routing is described below.

The request-local view contains canonical recipients and identity/lifetime witnesses
for adapters, clients, native apps, sockets and authorities. It is checked again
after history and after inference. A changed view rejects the whole message. These
checks are not a global transaction and cannot eliminate physical network races or
all ABA changes. The supported discovery domain is one GatewayRunner, including
its multiplexed profiles; independent processes are outside its native inventory.

## Context, judgment and delivery

1. Canonicalize supported authored text/rich text while preserving exact half-open
   Unicode ranges and source-field provenance. Quotes/code/forwarded material is
   inert reference. Reject unsupported media or inseparable composition.
2. Start with one `conversations_replies` page through the receiving workspace client
   with exact channel/root, pinned `latest=current timestamp`, `inclusive=False`,
   `limit=7`, initially no cursor and no time-window scan. Native HTTP qualification observed
   selection of the newest seven before cutoff in ascending internal order, plus
   the root (eight records); a verbatim cursor returned strictly older replies.
   Same-cutoff `limit=100` corroborated the selected seven. This supported-endpoint
   observation differs from inferring oldest-first selection from Slack's documented
   earliest-first ordering; it is not a global Slack behavior guarantee.
   Accept at most eight records, requiring exactly one known-ID root for an extra
   record. Identify root by `thread.root`, never position or count. When absent,
   use only documented `conversations_history(channel, oldest=root, inclusive=True,
   limit=1)`, requiring exactly the matching timestamp and valid supplied thread,
   workspace/channel fields. Never substitute an arbitrary channel record. Short
   pages are permitted by Slack's pagination contract. After deduplication/cutoff
   filtering, follow only the returned opaque older cursor if fewer than seven
   distinct prior replies remain. Keep the query pinned, validate ascending order
   within each page, and merge pages by exact timestamp, retaining the newest seven.
   Later pages may overlap known IDs; new replies must be older than the previous
   window. A nonempty cursor indicates continuation even with missing/false
   `has_more`; an empty or duplicate-only continuing page is not exhaustion. Stop
   immediately at seven, or allow a genuinely short thread on true terminal
   exhaustion. Repeated cursors and uncompleted bounded fill reject as
   `incomplete-context`, never partial semantic evidence. At most four SDK calls
   including optional exact root remain the count bound, without an elapsed cutoff.
   Root-trigger input makes no history call. Do not interpret live
   `reply_count`/`latest_reply` as a cutoff snapshot: they may reflect newer replies.
   Validate timestamps, scope, ascending reply order and duplicate fingerprints;
   reject future/foreign/malformed/conflicting records. Exact-cutoff records are
   excluded, identical duplicates deduplicated, and root is pinned independently
   of the seven strictly-prior replies. Once seven exist, older cursors do not
   require retrieval or cause a page-limit failure. Malformed response/cursor
   metadata still fails closed.
   These are acquisition bounds. Canonicalize only selected root/recent bodies with original authors/IDs/field
   provenance. Historical native bot `markdown` and text-only `section` blocks keep
   their visible leaf text/source paths, not notification fallback. Unknown blocks,
   selected media and missing authors fail closed; older unrequested media does
   not veto this view. CURRENT rich-text admission is unchanged. No cache/store exists.
3. The selected experimental `shared-routing-contract-v1` (S1C1) sends `whoami`,
   `current_author_content`, `conversation`, `people`, `native_delivery` and `source_selection`. Ordered
   conversation records run oldest to newest, with CURRENT last, carrying exact
   timestamp/event identity, inline sender/kind, order, text and provenance.
   Source-derived ROOT_HISTORY/HISTORY/CURRENT/CURRENT_ROOT tags distinguish root
   from an immediate predecessor; edited root retains its separate event identity.
   Unknown/null and genuine empty identity values remain distinct. Every body
   appears once in the conversation array; exact CURRENT segment text and Unicode
   offsets remain in `source_selection.segments`. The dropped current-parts/excerpt
   presentation adds no retained source alias or preview copying rule. Compact
   worked_contrasts in the two primary question instructions illustrate independent
   artifact masks, coordinated direct address, complete rejection/support, inert
   quotes versus fresh discussion and explicit eligible joint IDs, now extended by
   direct short-name/shared-name contrasts, an aligned Japanese/English artifact
   variant and standalone declarative rejection/reason/question support. These are disjoint
   hypothetical source masks, not actual option IDs or new routing authority.
   The direct-name/main exception is synchronized for response/scope; other v2
   definitions/rules/old illustrations remain unchanged. No notification fallback,
   inferred role or source fact replaces them. All contextual people remain in a
   deterministic array; eligible native IDs remain separate, not inferred owners.
   Optional `uI_priorJ` questions reference `conversation.records[J]` directly;
   no protocol/notice/prior-pointer aliases are inserted into conversation state.
   Protocol coherent-response-v1 and all raw witnesses/bindings stay local and
   unchanged. Acquisition still fixes exact root/latest-seven/order/cutoffs and
   does not refetch or prune. Test-local inverses prove old/new evidence equality;
   production contains no old-layout or control-arm selector. After acquisition,
   the exact serialized-request fitter may omit whole oldest non-root records;
   conversation.window states that factual boundary without new routing rules.
   Native discovery obtains request-local whoami from the participating transport's
   same-workspace authenticated `users.info`, validating returned team/user/is_bot.
   user_id, username, display_name and supplementary real_name remain distinct.
   Only native auth.test bot username may fill an unavailable username; empty names
   remain empty and unavailable fields are null. Never synthesize persona/profile
   aliases or reinterpret a real-name-fallback display cache as display_name.
   Metadata retrieval stays parallel with existing context acquisition, without
   an elapsed cutoff. Exact whoami data is added to the immutable source binding.
   A separate request-local `context_people` binding covers the unique CURRENT,
   root/latest-seven authors plus native candidates, at most13 people. It is not
   eligibility. Serving-workspace users.info resolves only missing authors, in
   parallel without a plugin timeout; current sender data is reused
   from native admission and candidate fields are reused without display-cache
   reinterpretation. Every row has separate ID/username/display_name/real_name
   and validated human/bot/unknown kind. Inline sender and directory are identical.
   Each utterance exposes source-derived order, exact timestamp and event identity.
   History is strictly before CURRENT; root is not an immediate predecessor or
   permanent owner, and the bounded window can omit middle events. Each independent
   question explains newer clear human same-topic handoffs, unrelated status,
   historical role/proposal evidence versus re-executing tasks/approvals, and repair
   subjects versus conversational addressees. No local role fold or extra gate runs.
4. ONE native `response` yes/no judges whether this receiver should respond to
   complete CURRENT UNDER THE ROUTING POLICY, never each punctuation fragment.
   Structured instructions/criteria separate current address, relevant reply
   author/same-task owner, general main fallback, same-scope chronological revision,
   explicit co-leads, ambiguous alternatives and accepted mixed-joint participation.
   Historical assignment is evidence, not fresh work/approval. An explicit revision
   by the original assigning speaker remains evidence when kind is unknown, without
   fabricating human authority. Fixed disjoint contrasts are not evaluation cases. A second
   speculative `scope` assumes admission and selects the complete exact extent:
   every deterministic nonempty authored-span subset plus unsafe, no none choice.
   Scope is only source selection, NOT another response/readiness/work judgment.
   Questions, explanations, requested acknowledgements, work and necessary
   supporting clauses/parentheticals qualify; an imperative is not required. Pure
   unsolicited courtesy/data and quoted commands do not independently request a
   response. Interpret slices with full CURRENT/root/recent/whoami; punctuation is
   not a declaration that tasks or addressees are independent. Current explicit
   addressing governs coordinated clauses until it changes addressee, not permanent
   main election. Preserve actual same-task authorship, general main fallback,
   later handoffs and genuine joint sets. Shared-name alternatives are not joint
   intent; a related placement check alone is not diagram-edit ownership. Inseparable
   meaning/identity uncertainty excludes that scope; outside co-assignees alone do not.
   An unrelated
   independent topic does not veto a resolved unit. No local assignment/name rule,
   peer-confidence ballot or executable-work certificate runs. Rejection,
   qualification and necessary supporting explanation clauses belong together.
5. Validate ALL exact wire keys/types, finite numbers, closed choices, probability
   distributions and selected argmax before consumption, including dormant scope
   and unused priors. Admit response YES only at native confidence strictly
   >0.5, ONCE. NO/low YES ignores valid scope and is silent. Admitted YES consumes
   the complete selected scope WITHOUT another confidence gate, even at zero valid
   scope confidence. Unsafe yields distinct projection-unresolved fidelity failure,
   never semantic NO or a whole-CURRENT fallback. Optional `uN_priorH` includes only at
   >=0.8 for an already selected unit; otherwise omit. Priors never select recipients
   or veto response. Unknown families, including old self_recipient/projection,
   reject. Code assembles selected exact native source spans into existing Unit/Plan,
   never whole mixed CURRENT, arbitrary substrings, confidence sums or probability
   substitutions. Protocol coherent-response-v1 rejects old fragment families.
   At most50 questions =response+scope+6*8 priors; scope has63 groups plus unsafe.
   Fully quoted sources generate no questions and no service call. Each plan serves
   only its bound receiver; other receivers are independent observations, not
   confidence barriers. Routing a response is NOT permission to execute an external
   action; downstream action authorization remains. Controlled checks are not
   semantic accuracy proof; all fixed required cases must qualify before adoption.
6. Deep-copy and project private Bolt `req.body` before native listener/busy handling.
   Each recipient gets its exact conversational response CURRENT spans and selected PRIOR text
   labeled “not instructions”, with prior mentions rendered non-wake-bearing.
   Preserve envelope identity and caller originals. Check projected CURRENT native
   admission separately; reference text cannot grant wake permission.
7. Recheck pending controls after awaits, including ordinary failures. Actual
   cancellation bypasses pending fallback. Ordinary unresolved
   input and nonrecipients stop with an empty acknowledgement before model, warning,
   steering or queue actions. Native exemptions pass through unchanged. Unload
   seals active callbacks against further inference/stale handoff; fresh quiescent
   post-unload requests pass through. Unload is not a cancellation trigger.

## Native admission and active-evaluation ownership

Before private inference, call the runner's definitive
`_is_user_authorized_for_source` on the actual native source (authorization home,
not routed runtime). Identity-resolution lookups in bind still precede that check.
Delegate original and own-CURRENT admission to `_channel_gate_allows`, using real
native mention detection and reply coordinates. Native wake/caches remain native;
do not claim pure/once-only wake evaluation. Derive each peer's session thread with
its own `_session_thread_ts`; history root is a separate coordinate. Revalidate the
whole topology after the awaited own-CURRENT gate, not before it. Keep the exact
projection proof/backfill/source checks and native downstream authorization.

Each awaited evaluation (including bind) is tracked in `adapter._background_tasks`,
never in native session-owner registries. A per-Gate active map holds source
workspace/channel/original ts, sender/root and the true explicit edited.ts revision
plus live tasks, not assignments, content or saved decisions. Invalidate before
awaiting cleanup on newer revisions; equal duplicates/distinct messages do not
cancel. Re-check ownership before native handoff, including late transport results
after cancellation. Use native `_normalize_changed_message`; outer event_ts or an
unfurl-only notification is not a revision. Native shutdown cancels/awaits tracked
cooperative I/O. No shield/detached inference, watcher, timeout or new hook exists.
After handoff native processed-message/queue/turn semantics remain authoritative;
this does not retract work. Quiescent unload is supported, concurrent hot-unload
during native hydration is not guaranteed. The host's own bounded teardown of
non-cooperative tasks is unchanged and is not a plugin cutoff or successful-join claim.

## Official API and credentials

`JevClient` uses asynchronous `httpx` POST to
`https://api.typesafe.ai/v1/systemone`, with Bearer authentication and JSON
`model: jev-latest`, `state`, and named `questions`. It consumes typed `answers`.
There is no subprocess, Jev CLI authentication or separate credential store.

Inference enters the runner's `_async_profile_scope_for_source`. Each ask resolves
`agent.secret_scope.get_secret("TYPESAFE_API_KEY")` within the actual serving
runtime, not a cached receiving-profile key. Hermes owns secret hydration. An
unscoped multiplex request or missing key fails before HTTP client creation.
Peer discovery does not read peer credentials.

TLS verification stays on. Redirects, environment proxies, retries and compressed
responses are disabled. Non-200, external transport errors, body-size, JSON and typed-answer
failures produce no ordinary work; response bodies and credentials are not logged.
The request owns and closes its asynchronous response/client on cancellation.
The HTTP client explicitly disables all httpx timeout phases with `timeout=None`.
Actual external transport timeouts are diagnosed as `transport-timeout`, not a
router deadline. Acquisition failures cancel and drain sibling reads; caller
`CancelledError` propagates even if native pending state appears concurrently.

Acquire at most eight distinct historical records; current units remain six, recipients four,
questions at50 for the maximum six-unit/eight-prior/four-recipient shape. Serialized Jev request and
response limits are 524,288 and 262,144 bytes respectively. Full CURRENT/ROOT and
retained original/provenance witnesses are not shortened by per-record text/raw caps.
Decoded Slack responses stay bounded at 1 MiB each (at most 4 MiB across
four SDK calls, including optional exact root). SDK JSON buffering precedes those checks: these
are acceptance limits, not hard socket/RSS limits. SDK retry behavior is unchanged,
so one replies invocation need not mean one wire attempt. No router-owned elapsed
abort, deadline parameter or timeout tunable remains in ingress, history,
presentation lookup or inference. Native/framework-owned transport behavior is
unchanged. This is not a claim of live acknowledgement safety, message-edit or
Gateway-end timing guarantees. Cooperative active evaluations now participate in
native shutdown; native transport/lifecycle bounds themselves remain unchanged.
Slack history has no atomic snapshot; unseen concurrent edits/deletions can race
even a valid newest-page view.

Before the single ask, repeatedly prepare and serialize the whole candidate source.
Only request-oversized removes the oldest whole non-root History record. Rebuild
all conversation orders/pointers/questions/answer keys and discard-only directory
authors; preserve candidate identities/labels and exact retained originals. Ask and
assemble use that same fitted Snapshot/batch. No refill/fetch, model retry, summary,
source slicing or second serializer runs. Protected CURRENT/ROOT-only excess gives
local `unsupported-request-size` at stage=fit, numeric bytes/dropped diagnostics,
no HTTP and no semantic NO or new Slack UX. Invalid encoding/NaN is separate.
Response status/size/encoding/Choice failures close resources and never refit/retry.

## Integration boundaries

The host compatibility target is Hermes v0.22.5 at
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`:

- `gateway/authz_mixin.py`: native primary/profile transport maps and ownership.
- `gateway/session_identity.py`, `gateway/session_authorities.py`: canonical
  transport/runtime identity and current serving authority.
- `gateway/platforms/base.py`: source building, plugin factory wiring and native
  dispatch/queue behavior.
- `plugins/platforms/slack/adapter.py`: authenticated workspace identities, socket
  state, Bolt listeners and Slack admission.
- `gateway/run_plugin_rewire.py`: late factory attachment and native app rewiring.

The public platform-handler registration is combined with private host fields and
Bolt body projection. Other host versions need explicit native qualification.
Native factory deduplication limits same-client unload/re-enable; a rebuilt app can
wire again. Candidate discovery does not imply that a peer received the channel
event or installed this plugin. Selective routing applies to activated receivers.

There is no plugin database, durable assignment/decision/transcript store or
operator registry. Host history/session/dedup behavior remains native. Repeated
events may infer different plans; no cross-process consensus, durable unresolved
queue or exactly-once delivery is promised. External processing requires operator
authorization for the conversation, not merely Slack read permission.

References: [Hermes plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins),
[System One API](https://docs.typesafe.ai/api.md),
[Bolt middleware](https://docs.slack.dev/tools/bolt-python/concepts/global-middleware/),
and [testing](native-acceptance.md).
Slack ordering and pagination: [conversations.replies](https://docs.slack.dev/reference/methods/conversations.replies/).
Known-root lookup: [conversations.history](https://docs.slack.dev/reference/methods/conversations.history/).
Short pages and continuation: [Slack pagination](https://docs.slack.dev/apis/web-api/pagination/).
