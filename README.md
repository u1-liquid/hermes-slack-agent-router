# Hermes Slack Agent Router

Context-aware multi-agent Slack message routing for Hermes, powered by Jev.
Jev identifies which earlier message, person
and topic each current instruction addresses. Each eligible agent receives only
its own actionable CURRENT spans and selected, explicitly inert PRIOR references.
A message can address several agents with different work.

## Install and use

Requires Python 3.11+, Hermes v0.22.5 at
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`, and its working Slack integration.
The native integration uses private host seams and is tested against that exact
revision. Package metadata alone does not establish compatibility with other hosts.

Use Hermes's native plugin manager from the repository root, pinned to a reviewed
full 40-character commit. Replace `REVIEWED_COMMIT_SHA` below with that immutable
revision (not a branch or tag):

```sh
hermes plugins install https://github.com/u1-liquid/hermes-slack-agent-router.git --ref REVIEWED_COMMIT_SHA --yes-deps --no-enable
hermes plugins enable slack-agent-router --no-allow-tool-override
hermes plugins list
hermes plugins doctor slack-agent-router --ci
```

The Git checkout root contains the native manifest and a registration re-export;
all routing implementation remains in the existing Python package. The adjacent
`pyproject.toml` supplies dependencies to Hermes PM. Do not inject packages into a
PM-selected environment with pip/uv. A wheel entry point remains available for
installation owners that supply their own Python environment; it is not the managed
installation recipe. Both layouts register the sole ID `slack-agent-router`.

The distribution is `hermes-slack-agent-router`, the Python package is
`hermes_slack_agent_router`, and the native plugin/entry point is `slack-agent-router`.
No legacy package or plugin alias is installed.

Enable it for every receiving profile that should use selective routing. Use the
normal Hermes secret setup to make `TYPESAFE_API_KEY` available to each profile
that actually executes requests. The plugin resolves that key inside the serving
runtime's native secret scope, which may differ from the receiving bot's profile.
It does not use a Jev executable or a TypeSafe SDK.

There is no plugin configuration file, participant list, input-policy registry,
initialization command or manual thread-owner setup. After native activation,
eligible messages use the connected Slack transports already owned by the gateway.
Plugin Doctor checks registration; it does not prove socket readiness or delivery.

For example, if native history establishes that Atlas prepared a summary and Birch
prepared a diagram, “Atlas, revise the summary; Birch, check the diagram” can produce
two different recipient inputs. “Please continue” needs unambiguous prior evidence
of a general conversational lead. It does not establish a permanent owner.

## Participation and external processing

Candidates come from the current GatewayRunner's primary and multiplexed-profile
Slack adapters. Each candidate needs authenticated identity in the same Slack
workspace, a live native socket and a served runtime. Native source routing is
resolved separately for each transport and this sender/channel/thread; configured
profiles, display names, history authors and human allowlists are not participants.

Discovery is limited to one GatewayRunner. It does not discover agents in other
processes or on other hosts. A shared bot contributes one event-specific native
runtime, not one candidate per configured profile. A disconnected bot is not a
candidate. Unknown or ambiguous identity, duplicate bot ownership, or a topology
change during evaluation yields no ordinary work. There is no hidden all-agent
or receiver-only fallback. Native policy still decides whether each receiver may act;
a discovered peer is not proof of channel membership or delivery.

Eligible current text, bounded prior text, source authors and candidate bot/runtime
identities are sent to `https://api.typesafe.ai/v1/systemone` using `jev-latest`.
Enable this plugin only where you are authorized to send that conversation to
TypeSafe. Slack read access is not external-processing consent. There is no plugin
privacy classifier or per-channel egress-policy setting. Missing serving-profile
credentials or invalid responses result in no ordinary work. Production does not
log keys, transcripts or service error bodies, or store routing decisions.

## Behavior and limits

- Jev returns closed-set typed decisions, not executable text. Relevant confidence
  must be at least 0.8; source grounding and complete instruction coverage are checked.
  Uncertainty in any actionable unit rejects the whole message, not just one clause.
- Replies use the actual latest seven messages strictly before the trigger, plus
  the verified root even outside that window. Overlap is represented once. On the
  qualified native endpoint, one `conversations.replies` request with `limit=7`,
  `latest=current timestamp`, `inclusive=false` and no cursor returns the newest
  bounded subset in ascending internal order, normally root plus seven replies.
  A returned cursor leads to older history and is ignored once seven distinct
  strictly-prior replies exist. Slack may return a short page: only when fewer than
  seven remain after deduplication/current exclusion does acquisition follow that
  opaque cursor, with the same query, until seven or true exhaustion. Empty or
  duplicate-only pages with advancing cursors do not establish exhaustion; a cursor
  continues even when `has_more` is false/missing. This is an observed
  supported-endpoint contract, not a universal guarantee inferred from page ordering:
  Slack's documentation describes earliest-first order within the time range.
- Informative recent message/person/topic evidence takes priority. Root context is
  used only when recent messages provide no relevant assignee support. A newer clear
  handoff overrides an older assignment; unresolved conflict or failed retrieval does
  not become root fallback. A human root author or first mention is not automatically
  the owner. Current explicit specific instructions retain priority. Topic-only recent
  context does not erase a supported root assignee. Historical joint assignments
  preserve their exact recipient set, rather than becoming an all-agent fallback.
- Retrieval normally uses one SDK replies call; short-tail fill and, only if root
  is absent, one exact `conversations.history(oldest=root, inclusive=true, limit=1)`
  lookup share a maximum of four SDK calls. Root identity and every supplied
  thread/workspace/channel field must match; no arbitrary result substitutes for it.
  All calls share one second, ending before the ingress deadline minus 1.3 seconds.
  Live root `reply_count`/`latest_reply` are not cutoff snapshots.
  Missing/unverifiable roots, cursor loops, exhausted bounds without a complete
  tail, and malformed, foreign/future/conflicting records yield no work. Each decoded
  response is capped at 1 MiB (at most 4 MiB across four calls), not a pre-download
  memory cap. Native SDK retries may add wire attempts. Slack has no atomic history
  snapshot; unseen concurrent edits/deletions can race.
- Current input is limited to 6,000 characters, six units, four recipients and
  174 questions. Up to eight distinct prior records have 6,000 characters each
  (48,000 aggregate), with a 64 KiB retained original-record limit. The Jev request
  limit is 524,288 bytes; its response limit is 262,144 bytes. Nothing is silently
  truncated. Selected media and inseparable authored/reference composition are unsupported.
  Prior bot responses support native `markdown` and text-only `section` blocks,
  retaining their visible text and exact leaf provenance rather than replacing them
  with notification fallback text. Unknown blocks, section fields/accessories and
  missing user identities still reject the view. Human CURRENT block support is
  unchanged (`rich_text` only); prior block support grants no current admission.
- The ingress budget is 2.5 seconds, including context and the at-most-1.2-second
  Jev request. These are engineering deadlines, not hard real-time guarantees.
  Jev TLS is verified; redirects, environment proxies and automatic Jev retries are disabled.
- Original and projected native sender/channel/mention/wake policy must permit the
  request. Commands, DMs/MPIMs, bots/self and native pending approval, clarification,
  confirmation and update controls retain native handling. Inferred recipients do
  not grant authority. Monitoring bots follow native bot policy.
- Normal, busy, queue, merge and replay paths receive scoped text. A nonrecipient or
  unresolved ordinary message gets an empty transport acknowledgement, no main-model
  call, queue/steering action or silence warning. Fixed local diagnostics explain
  unresolved input without exposing its content.
- The plugin keeps only request-local state. Hermes owns history, sessions, queues
  and deduplication. Separate ingress events can classify again and stochastic
  decisions can differ; there is no cross-process consensus or exactly-once promise.

## Troubleshooting and disabling

If registration succeeds but routing does not, check the native Slack connection,
served profile, serving-profile key and bounded newest-page root/recent view. Local codes such as
`missing-root-context`, `unsupported-prior-composition`,
`incomplete-context`, `native-topology-unresolved`, `native-topology-changed`, `classifier-failed` and
`coverage-or-grounding-unresolved` distinguish bounded failures. Fetch diagnostics
separate `context-fetch-not-permitted` (including unavailable channel access),
`context-fetch-rate-limited`, `context-fetch-timeout`, `context-fetch-api-failed`
and `context-fetch-failed` (SDK/transport). They never print raw API error bodies.
The pinned adapter uses its authenticated workspace client for history; there is no
separate native user/history client. Resolve access failures through the existing
Slack integration, not a plugin credential store or borrowed integration token.
`ingress-failed`
can indicate unavailable native identity/lifecycle seams. Do not paste private input
or credentials into diagnostics to investigate them.

New connected adapters are discovered on later requests. Reconnecting to a rebuilt
native app rewires the factory. On this pinned host, disabling disposes retained
callbacks into pass-through, but does not physically remove them. Same-client
unload/re-enable is not a supported hot replacement: native factory deduplication
can prevent a new callback from attaching. Use a normally managed fresh gateway
lifecycle when activating a replacement; plugin commands alone do not prove it active.
A disabled or broken plugin is not a universal fail-closed enforcement boundary.

```sh
hermes plugins disable slack-agent-router
hermes plugins remove slack-agent-router
```

## Development and verification

See [design](docs/design.md) for data flow and native boundaries and
[testing](docs/native-acceptance.md) for runnable offline and opt-in fictional tests.
CI has distinct `core` and `native` jobs, both on Python 3.14, using
`actions/checkout@v7` and `actions/setup-python@v7`. Offline tests require
no real TypeSafe key. Passing controlled tests is not a live Slack deployment check
or a guarantee of classifier accuracy.

The Dependabot configuration groups version-update proposals by ecosystem, with
separate security-update groups. It checks Actions and Python dependencies weekly
on Monday at 09:00 Asia/Tokyo. The root Python updater covers `pyproject.toml` and
`tests/requirements-native.txt`; arbitrary version strings in shell commands are
not Python manifest coverage. Dependabot reads this configuration from the default
branch: a feature-branch file alone is not activation or proof of updater execution.
There is no automatic merge policy.

MIT license, copyright u1-liquid.
