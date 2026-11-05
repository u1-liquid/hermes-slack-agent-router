# Runtime design

## Transparent whole-message filter

`register(ctx)` attaches a Slack middleware factory. There is no delivery rewrite
or pre-dispatch hook. The `fallback-to-respond` policy suppresses only a valid
complete-message NO whose selected-answer native confidence is strictly >0.5.
YES at any confidence, NO<=0.5 and classification failures call ordinary native
handling once with the original complete Bolt body unchanged. Class probability
is validated but never used as confidence. Native downstream exceptions propagate;
the classifier catch never catches `next()` and never retries native processing.

One `response` choice question addresses this exact receiver's complete CURRENT.
The same ordered conversation/people reaches each receiver, with only `whoami`
identifying which native receiver is being evaluated. Text and supported structured
Slack blocks are retained whole, including quote, preformatted and inline-code
semantics. There are no segments, source-selection questions, subsets, conditional
scope, fragment votes, regrouping, extraction plan or compatibility flags.
Unsupported or malformed composition/media skips inference and passes unchanged;
it is never silently replaced by a notification fallback for classification.

Names identify people, not necessarily addressees. The ordered whole-message rules
retain general continuation/main/co-leads, specific-task ownership, genuine
same-task handoffs, explicit current addressing, same-name ambiguity, explanatory
rejection/support and explicit joint participation. NO requires positive evidence
excluding this exact receiver from every fresh response. Unknown/ambiguous
addressing, main or assignment alone is not exclusion. YES means an own response
exists or exclusion remains unresolved: fallback native continuation does not
prove ownership, joint intent or semantic accuracy. Any coherent own response is
sufficient for YES even if other tasks in CURRENT belong elsewhere. Every
nonexcluded receiver sees the full mixed original message, not a private task slice.
Intent is not authorization, consent or guaranteed execution by any participant.

## Native identity and admission boundary

Registration reads no configuration and requires no ready socket. Request-time
`Bridge.bind` resolves workspace, source sender ID, receiving bot, native source,
routed runtime and native session key. Commands, unsupported DMs/MPIMs and native
pending approval/clarification/confirmation/update controls bypass inference.
The plugin does not classify people or duplicate native user authorization,
channel allowlist/ignored-channel or mention/wake gates.
Supported ordinary messages may therefore reach history/metadata acquisition and
Jev before native admission, regardless of sender metadata or native policy. Native
Hermes still enforces its own rules on continuation; Bolt self-event middleware
may reject an event before the plugin runs. No sender is fabricated from bot_id.
External-processing consent is a profile-activation responsibility, never inferred
from Slack permissions or native allowlists.

Participants come from connected primary/multiplexed adapters' native workspace
maps. `_event_team_id`, `build_source`, `_canonicalize` and `_source_session_key`
own workspace resolution, source identity, runtime binding and session keys. The
plugin consumes their outputs directly: no user-ID regex, repeated workspace/ID
equality gates, home/name authorization registry or topology witnesses. Each lookup
uses the selected adapter's client for the request workspace, not another workspace's
client. There is no configured registry or workspace enumeration.
Each peer uses its own native `_session_thread_ts`,
independent of the conversation's acquisition root. Absent/null/self-root top-level
`thread_ts` uses CURRENT as root; native session coordinates still obey each peer's
`reply_in_thread`. Ordinary replies keep their real root. Native identities are not
revalidated after awaits; native lifecycle and downstream admission remain authoritative.

Metadata is request-local ID/username/display_name/real_name, not an entire Slack
profile or a bot/human category. Unknown optional names remain
null; genuine empty names remain empty. Sender and history authors share bounded
contextual lookup; no recipient classification is required. The selected native
client supplies names for native IDs without rechecking SDK user/team echoes.
SDK failure, malformed profile structure or invalid/beyond-bound name fields abort
classification instead of pretending acquisition succeeded. Name-field validation
occurs at acquisition, not again in semantic preparation. Per-request secret scope
is the actual native serving runtime's scope.

## Bounded context and exact byte fitting

Replies acquire exact root and latest seven strictly prior messages. The first
`conversations_replies` uses channel/root/latest=CURRENT/inclusive=False/limit=7.
Qualified newest-window selection and ascending within-page order are integration
assumptions; Slack's documented earliest-first page ordering alone does not prove
selection. Only short tails follow opaque older cursors to fill seven or prove
exhaustion. Root may be fetched by exact `conversations_history` oldest=root,
inclusive=True, limit=1. Acquisition uses at most four SDK calls and 1 MiB per decoded
response. CURRENT==root returns no history immediately, protecting one root record.

Validate SDK content structure, channel/thread selection, timestamps, order,
cutoff and duplicates; detect conflicting history with fingerprints. These
fingerprints protect acquisition consistency, not source
projection or native user/workspace admission. Future, wrong-channel/thread,
incomplete or unsupported history defers natively. SDK
buffering and native Slack retries precede these decoded bounds. History is not an
atomic snapshot and unseen edits/deletions can race.

The actual production compact UTF-8 serializer caps requests at 524,288 bytes.
Fitting removes only whole oldest non-root priors and now-unused contextual people,
then rebuilds ordered records. CURRENT and ROOT are never shortened or subdivided.
Protected-only oversize or invalid encoding defers without HTTP. Native history
and backfill are unaffected by the classifier's smaller window. The 262,144-byte
response cap is independent. Four recipients/13 people bound metadata, not text.

## Lifecycle and delivery

Active evaluation (including binding) is enrolled in the adapter's native background
tasks. A request-local Gate map holds native source coordinates, explicit
edit revision and live tasks only. Newer true edits invalidate before awaiting
obsolete tasks; stale active revisions and late cancelled results cannot hand off.
Equal duplicate envelopes, unfurl delivery timestamps and distinct newer messages
do not cancel current evaluation. Caller cancellation propagates. Gateway draining
and native adapter shutdown are terminal and drain cooperative resources. There is
no durable revision store or retraction of already handed-off/queued/running work.

Unload disables filtering, not native event delivery: live in-flight events pass
after owned work cleans up, regardless of a classifier NO. No fresh inference is
started after disposal. Caller/edit/shutdown cancellation still wins. Shutdown is
checked even for already disposed middleware. No body/text/blocks/files/attachments
or media/history field is replaced. Native normal, busy, merged, FIFO and replay
paths retain their ordinary formatting, backfill, permissions and deduplication.
Pass-through never forces native execution. Same-client re-enable retains the
native factory deduplication limitation; replacement needs the managed lifecycle.

## HTTP and qualification

`JevClient` sends System One Choice to `https://api.typesafe.ai/v1/systemone` with
`jev-latest`. Closed complete answer coverage, selected choice, finite numeric
range, distribution and argmax consistency are validated before returning choice
and native confidence unchanged. A stdlib object-pairs decoder rejects duplicate
JSON members at every nesting level before values collapse, including escaped
equivalent keys. Normal envelope metadata is compatible. Missing/extra/bad or
duplicate-member answers cannot synthesize NO; they use the payload-free fallback.
Per-request `agent.secret_scope.get_secret("TYPESAFE_API_KEY")` runs within the
actual serving runtime's `_async_profile_scope_for_source`. Missing key/scope
fails before HTTP creation. No alternate model, retry or local semantic fallback.

TLS verification is enabled; redirects/proxies/compressed responses and automatic
Jev retries are disabled. `timeout=None`; no plugin elapsed cutoff. Owned HTTP and
acquisition tasks close/drain on completion/failure/cancellation. Logs contain
only source-owned categories/numeric measurements, never raw errors or bodies.

The qualified official host is `f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab`, publicly
fetchable at NousResearch/hermes-agent. Prior bf0203a qualification is historical.
Private native seams require source-bound integration checks when changing hosts.
Controlled fictional tests do not prove live Slack delivery, semantic accuracy,
independent acceptance or installed runtime adoption. There is no DB, durable
owner/decision cache, cross-process consensus or exactly-once promise.

See [use/consent](../README.md), [testing](native-acceptance.md),
[Hermes plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins),
[System One](https://docs.typesafe.ai/api.md),
[Bolt middleware](https://docs.slack.dev/tools/bolt-python/concepts/global-middleware/),
[Slack replies](https://docs.slack.dev/reference/methods/conversations.replies/) and
[known-message lookup](https://docs.slack.dev/reference/methods/conversations.history/).