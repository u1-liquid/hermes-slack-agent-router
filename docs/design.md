# Hermes Slack Agent Router — runtime design

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
2. Fetch one `conversations_replies` page through the receiving workspace client
   with exact channel/root, pinned `latest=current timestamp`, `inclusive=False`,
   `limit=7`, no cursor and no time-window scan. Native HTTP qualification observed
   selection of the newest seven before cutoff in ascending internal order, plus
   the root (eight records); a verbatim cursor returned strictly older replies.
   Same-cutoff `limit=100` corroborated the selected seven. This supported-endpoint
   observation differs from inferring oldest-first selection from Slack's documented
   earliest-first ordering; it is not a global Slack behavior guarantee.
   Accept at most eight records, requiring exactly one known-ID root for an extra
   record. Identify root by `thread.root`, never position or count. When absent,
   use only documented `conversations_history(channel, oldest=root, inclusive=True,
   limit=1)`, requiring exactly the matching timestamp and valid supplied thread,
   workspace/channel fields. Never substitute an arbitrary channel record. Both
   calls share the existing one-second retrieval budget. Root-trigger input makes
   no history call. Do not interpret live `reply_count`/`latest_reply` as a cutoff
   snapshot: they may reflect newer replies.
   Validate timestamps, scope, ascending reply order and duplicate fingerprints;
   reject future/foreign/malformed/conflicting records. Exact-cutoff records are
   excluded, identical duplicates deduplicated, and root is pinned independently
   of the seven strictly-prior replies. Older cursors do not require retrieval or
   cause a page-limit failure. Malformed response/cursor metadata still fails closed.
   Canonicalize only selected root/recent bodies with original authors/IDs/field
   provenance. Historical native bot `markdown` and text-only `section` blocks keep
   their visible leaf text/source paths, not notification fallback. Unknown blocks,
   selected media and missing authors fail closed; older unrequested media does
   not veto this view. CURRENT rich-text admission is unchanged. No cache/store exists.
3. Build one typed question batch over current units, prior source authors/text and
   sorted recipients. There is no receiving-agent preference in the model input.
   Questions classify action/reference/acknowledgement, destination, CURRENT-only
   addressing/membership, local source context links and task/lead assignment facts.
   Specific actions use a coarse complete-address Choice: explicit registered set,
   nonexplicit (contextual person or unstated assignee), outside, mixed or unknown.
   Contextual and unstated cases consume the same local historical proof. A separate
   original fine address audit remains confidence-gated for ack/reference units,
   where contextual/explicit addressing contradicts nonaction; it is not consumed
   by specific actions. Generic actions consume neither address family, as before.
   Each historical fact describes only that message's own assignment, acceptance,
   proposal author or explicit takeover. It never judges later supersession or a
   globally selected recipient. Closed-set labels encode complete recipient subsets,
   including historical joint assignments; outside/mixed/disputed/unknown facts cannot
   silently become a partial registered set. Context links do not create membership.
4. Code derives precedence from validated local facts in timestamp order: matching
   ordinary assignments establish/confirm a recipient set; a different plain set
   creates conflict. An explicit complete takeover replaces the set and resolves a
   known preceding conflict/dispute, but cannot conceal an unknown/unsafe fact.
   Topic-only context does not change the assignee, so root fallback remains available
   when recent text does not identify/reassign/dispute it. Complete explicit CURRENT
   assignments control specific work, with local name/ID grounding. Generic work uses
   the same fold over whole-thread lead facts, independently of specific-task facts.
   Superseded incompatible assignment references are excluded deterministically;
   linked topic context stays inert. Human root authorship, first mention and mere
   participation are not ownership rules. Specific/joint work is independent of
   irrelevant general-lead uncertainty. No separate global tier/source verdict is asked.
5. Validate exact keys/types, finite distributions, relevant confidence of 0.8,
   source grounding, transitive topic relations and complete coverage. Assemble
   atomically: no invented instructions or identifiers, partial omission or fan-out
   fallback. Topic identities and plans exist only within this request.
6. Deep-copy and project private Bolt `req.body` before native listener/busy handling.
   Each recipient gets its exact actionable CURRENT spans and selected PRIOR text
   labeled “not instructions”, with prior mentions rendered non-wake-bearing.
   Preserve envelope identity and caller originals. Check projected CURRENT native
   admission separately; reference text cannot grant wake permission.
7. Recheck pending controls after awaits, including failures. Ordinary unresolved
   input and nonrecipients stop with an empty acknowledgement before model, warning,
   steering or queue actions. Native exemptions pass through unchanged. Unload
   disposes callbacks into pass-through, not physical removal.

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
responses are disabled. Non-200, transport, timeout, body-size, JSON and typed-answer
failures produce no ordinary work; response bodies and credentials are not logged.
The request owns and closes its asynchronous response/client on cancellation.

Current text is capped at 6,000 characters; selected history at eight distinct
records/6,000 characters each/48,000 total; current units at six, recipients at four,
questions at 174 (the maximum six-unit/eight-prior/four-recipient shape). Serialized Jev request and
response limits are 524,288 and 262,144 bytes respectively. Retained original records
are capped at 64 KiB; decoded Slack responses at 1 MiB each (at most 2 MiB for
replies plus optional exact root). SDK JSON buffering precedes those checks: these
are acceptance limits, not hard socket/RSS limits. SDK retry behavior is unchanged,
so one replies invocation need not mean one wire attempt. The 2.5-second ingress
budget includes context, with at most one second for retrieval (also bounded by
ingress deadline minus 1.3 seconds) and 1.2 seconds for Jev. Deadlines are not hard
real-time scheduling claims or proof of Slack acknowledgement safety on a live host.
Slack history has no atomic snapshot; unseen concurrent edits/deletions can race
even a valid newest-page view.

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
