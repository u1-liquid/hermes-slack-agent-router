# Runtime design

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
2. Fetch `conversations_replies` through the receiving workspace client with the
   exact channel/root, `latest=current timestamp`, `inclusive=False`, `limit=7`.
   Require a complete short history, exclude the current timestamp and validate
   root/workspace/channel/time identities. Deduplicate identical records and sort
   by original timestamp identity. No pagination cache or transcript store exists.
3. Build one typed question batch over current units, prior source authors/text and
   sorted recipients. There is no receiving-agent preference in the model input.
   Questions classify action/reference/acknowledgement, destination, source support,
   per-recipient membership and topic relationships.
4. A generic continuation uses a general-lead Choice plus independent evidence
   Choices for prior messages. Specific work does not need a known general lead.
   Mere participation or a secondary topic invitation does not establish that lead.
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

Current and prior text are each capped at 6,000 characters; history at six messages,
current units at six, recipients at four, questions at 96, and each serialized
request/response at 262,144 bytes. The 2.5-second ingress budget includes context,
with at most 1.2 seconds for Jev. Deadlines are not hard real-time scheduling claims.

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
