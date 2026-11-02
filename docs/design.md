# Runtime design

## Native participation and authority

`register(ctx)` registers a Slack middleware factory and a `pre_gateway_dispatch`
hook. It reads no plugin configuration and does not require a ready socket at
registration. Request-time discovery uses the current GatewayRunner's primary and
multiplexed-profile Slack adapters, not profile directories or a saved registry.

`Bridge.bind` resolves the workspace, human sender, receiving bot, native source,
routed runtime and session key. Native commands, bots/self, DMs/MPIMs and pending
approval, clarification, confirmation or update controls retain their native path.
The runner's definitive `_is_user_authorized_for_source` check uses the transport's
authorization home before history acquisition or private inference. Identity reads
needed to bind the source can precede it.

Each participant needs same-workspace authenticated identity, a live socket and
served transport/runtime authorities. Each peer builds its own event-specific
source using native session thread coordinates; those are separate from the
history root. A shared bot is not multiplied into one candidate per configured
profile. Duplicate bot ownership, unknown identity or an inconsistent topology
rejects ordinary work. Topology is rechecked after awaited acquisition and after
projected-CURRENT admission. These witnesses are not a global transaction and
cannot eliminate all network or ABA races.

## Exact source and context

Supported authored text/rich text is flattened with exact half-open Unicode
ranges, leaf paths and preserved originals. Quotes, code and forwarded material
remain inert. CURRENT supports rich text; PRIOR also supports native markdown,
text-only sections and text-only context blocks. Unsupported or mixed composition
is not replaced by notification fallback text. Selected media is unsupported.

For a reply, history starts with `conversations_replies(channel, ts=root,
latest=current_timestamp, inclusive=False, limit=7)`, without a cursor. On the
qualified endpoint, this selects the newest bounded subset in ascending internal
order, normally root plus seven replies. Slack's documented earliest-first page
ordering alone does not establish that selection contract.

Only a short tail follows the returned opaque older cursor, with the same cutoff,
until seven distinct replies or true exhaustion. Advancing empty/duplicate-only
pages do not prove exhaustion; a cursor still matters when `has_more` is false or
missing. Once seven replies exist, older cursors are ignored. If root is absent,
`conversations_history(channel, oldest=root, inclusive=True, limit=1)` must return
that exact root. At most four SDK calls, including that lookup, are permitted.
Root-trigger input makes no history call.

Timestamp, scope, order, cutoff and duplicate fingerprints are validated. Foreign,
future, conflicting, malformed or incomplete context rejects the request. Live
root reply counts are not cutoff snapshots. Each decoded response is capped at
1 MiB; SDK buffering precedes validation and retries can add wire attempts. Slack
provides no atomic history snapshot, so unseen concurrent edits/deletions can race.

Request-local identity metadata includes exact IDs, distinct username/display_name/
real_name fields and human/bot/unknown kind. `users.info` data must match the
workspace and user; unavailable fields stay null and genuine empty names stay
empty. Only the native authenticated bot username is a fallback. The people
directory covers source-window authors and candidates, at most 13 people, and is
not a recipient registry. Only missing authors are looked up on the serving
client; there is no workspace enumeration or persistent metadata cache.

## Whole-message decision and exact extraction

The model sees the same complete oldest-to-newest conversation and people for
each receiver, with receiver identity in `whoami`, native eligible IDs separately,
and exact CURRENT segments in `source_selection`. `current_author_content` is
literal unquoted source evidence, not a locally computed request or recipient.
Both primary questions share the same ordered routing contract. The current
prompt and its fictional contrasts remain behavior-sensitive source, not a local
name/role parser.

`response` asks once whether a coherent response belongs to this exact receiver.
YES admits only at native confidence strictly greater than 0.5; NO and low YES are
silent. Probability cannot replace confidence. A response can be a question,
explanation, requested acknowledgement or work, with its necessary support.

Conditional `scope` assumes admission and selects the complete exact own-source
extent from nonempty authored-segment groups plus `unsafe`. It has no second
confidence, readiness or executable-work gate. Punctuation does not create
independent response ballots. `unsafe` produces `projection-unresolved`, not a
semantic NO, partial request or whole mixed-CURRENT fallback. All answer fields,
including dormant scope and unused priors, receive closed-choice, finite-number,
distribution and argmax validation before consumption. Optional prior-reference
choices retain include only at native confidence at least 0.8 for selected units;
they cannot select a recipient or veto a response.

Addressing is distinct from identity matching. General continuation, including a
bare no-@ name call, can stay with evidenced main/co-leads; this neither invents
main nor overrides specific-topic ownership, genuine handoff or native @. Newer
clear same-scope revisions supersede older assignments for that scope only.
Historical proposals/approvals are evidence, not fresh execution authority. An
eligible bot may participate in a genuine joint request with humans or outsiders
without claiming their receipt, consent or execution. Unresolved same-name
alternatives are not joint membership. An independent foreign topic does not veto
an otherwise resolved own response.

Acquisition allows eight distinct prior records, CURRENT six segments and four
native recipients. The maximum 50 questions are response, scope and 48 optional
priors; scope has at most 63 nonempty groups plus unsafe. Fully quoted CURRENT
requires no inference. Actual compact UTF-8 serialization must fit 524,288 bytes.
The fitter removes whole oldest non-root priors, rebuilding indices, questions
and the source-derived people directory. CURRENT and ROOT are never shortened.
Protected-only excess yields local `unsupported-request-size` without HTTP;
invalid serialization and response failures do not trigger fitting or retries.
The response limit is independently 262,144 bytes.

## Delivery and lifecycle

A private deep copy of Bolt `req.body` receives the exact own CURRENT and selected
PRIOR text labelled “not instructions”; prior mentions are rendered non-wake-bearing.
The original envelope identity and caller body are preserved. Own CURRENT alone
must pass the real native `_channel_gate_allows` predicate before handoff: inert
references cannot grant wake permission. No duplicate plugin allowlist runs.

The request-local Python closure carried into `pre_gateway_dispatch` binds the
source, sender, receiver, runtime, runner and session. It cannot arrive in Slack
JSON. The hook checks it before discarding newly hydrated channel/reply/media
backfill, then removes the closure before native snapshots. This is native source
isolation, not semantic certification. Normal, busy, merge, FIFO and replay paths
consume the scoped input. Existing native session memory and downstream action
authorization are not erased or replaced.

Active evaluation is enrolled in `adapter._background_tasks`, including binding.
A per-Gate map contains only original source coordinates, sender/root, explicit
`edited.ts` revision and live tasks. Newer true edits invalidate before awaiting
obsolete work; equal envelope duplicates, unfurl event IDs and later distinct
messages do not cancel evaluation. Late cancelled results cannot hand off or
resurrect original text through pending fallback. Native shutdown drains
cooperative I/O; the host's noncooperative teardown bounds remain unchanged.
This does not retract already handed-off work or clear native processed claims.

Unload seals active callbacks against new inference/stale handoff without being
a cancellation trigger. Quiescent post-unload requests pass through. Concurrent
hot-unload during native hydration and same-client re-enable are not guaranteed;
a managed fresh gateway lifecycle is required for replacement activation.

## Transport and compatibility

`JevClient` sends typed Choice requests to
`https://api.typesafe.ai/v1/systemone` with `model: jev-latest`. Every ask resolves
`agent.secret_scope.get_secret("TYPESAFE_API_KEY")` inside the runner's actual
`_async_profile_scope_for_source`; missing scope/key fails before client creation.
No CLI, SDK, copied key, alternate model or local semantic fallback is used.

TLS is verified. Redirects, environment proxies, compressed responses and automatic
Jev retries are disabled. HTTP resources close on failure/cancellation. `httpx`
uses `timeout=None`; the router has no elapsed cutoff on ingress, acquisition,
metadata or inference. Actual external transport errors still fail safely.
Diagnostics contain source-owned codes and numeric measurements, not arbitrary
exception bodies, transcripts or credentials.

The supported host is Hermes v0.22.5 at
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`. Private integration points include native
identity/authority maps, source builders, Slack admission, Bolt middleware and
factory rewiring. Other revisions need native qualification. Discovery is
runner-local and does not prove a peer received an event or enabled the plugin.
There is no plugin DB, durable owner/decision store, operator registry or
cross-process exactly-once promise.

See [use and external-processing consent](../README.md) and
[controlled testing](native-acceptance.md). API references:
[Hermes plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins),
[System One](https://docs.typesafe.ai/api.md),
[Bolt middleware](https://docs.slack.dev/tools/bolt-python/concepts/global-middleware/),
[Slack replies](https://docs.slack.dev/reference/methods/conversations.replies/),
[known-message lookup](https://docs.slack.dev/reference/methods/conversations.history/)
and [pagination](https://docs.slack.dev/apis/web-api/pagination/).
