# Hermes Slack Agent Router

Context-aware multi-agent Slack message routing for Hermes, powered by Jev.
Jev identifies which earlier message, person
and topic each current instruction addresses. Each eligible agent receives only
its own actionable CURRENT spans and selected, explicitly inert PRIOR references.
A message can address several agents with different work.

The working candidate is yes05-joint-v1 on lossless readable-rubric-v2, retaining
the worked contrasts and separate exact source segments. A fresh unambiguous name,
including a short/given form resolved by supplied names/context, needs no prior task
ownership to identify its referent; it is not a mandatory handoff away from known
main for a bare no-@ call/general conversation continuation without independent
specific-topic allocation, assignment or genuine handoff. Main stays the target in
that case, not reply-all or activation of the other named agent. Native @ and genuine
topic owners/handoffs remain distinct; no absent main is invented and not all no-@
goes to main. Only colliding supplied names need actual same-task resolution. Native
authority remains separate. `current_author_content` adds literal unquoted CURRENT
text and exact quoted/reference paths, not a computed request/recipient. Complete
original source remains. Fixed disjoint illustrations add shared-name contrasts,
aligned Japanese/English independent artifacts and declarative support. No rejected
CURRENT.parts/excerpts return. One whole-message gate, repaired native fixture
and full-view-native-v2 assertion remain unchanged. Controlled checks and example
presence are not semantic qualification or independent acceptance; no install/restart
follows from this work. See docs/native-acceptance.md for the fixed full campaign.

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

For the complete CURRENT and actual bound receiver, ONE native `response` yes/no
asks whether a conversational response is requested. Only YES with native confidence
strictly greater than0.5 admits the coherent request, once. NO/low YES is silence.
The same official request includes ONE conditional `scope` choice: assuming admission,
select the COMPLETE exact source extent from generated nonempty span subsets or
`unsafe`. It has NO second confidence/work/readiness gate and NO none alternative.
Valid low scope confidence cannot trim or veto an admitted request. Unsafe means
no faithful own extent is representable; it is distinct projection-unresolved
fidelity failure, not successful semantic NO. No whole mixed-CURRENT fallback runs.
Questions, explanations, requested acknowledgements, work and necessary supporting
clauses can qualify. Punctuation slices are not independent-task declarations.
Current explicit addressing carries across coordinated clauses until the addressee
changes, without electing a permanent main. An unrelated independent topic does
not veto a resolved response; inseparable meaning/identity/joint-member uncertainty
still cannot be chopped or shrunk into a partial instruction.

Canonical root, recent and CURRENT utterances carry their exact timestamp and
author UID inline, with verified native names only when already available. Unknown
authors remain UID-only. Visible rich-text bodies are not replaced by notification
fallback text; all competing candidates remain visible. Equal names alone do not
force rejection when same-task authorship/assignment/handoff or explicit IDs resolve
the intended actor. Conversely possible same-name alternatives are not a genuine
joint request, and related-task participation alone is not ownership of another artifact.

## Participation and external processing

Candidates come from the current GatewayRunner's primary and multiplexed-profile
Slack adapters. Each candidate needs authenticated identity in the same Slack
workspace, a live native socket and a served runtime. Native source routing is
resolved separately for each transport and this sender/channel/thread; configured
profiles, display names, history authors and human allowlists do not establish native delivery eligibility.
The request-local people directory separately includes CURRENT/root/latest-seven human and bot authors plus verified native candidates (at most13 people, still only four eligible recipients). It carries exact IDs, separate username/display_name/real_name and validated human/bot/unknown kind; missing metadata stays explicit. Serving-client users.info reads only missing source-window author IDs, deduped within the existing acquisition deadline. No workspace enumeration or persistent people registry runs. Inline sender metadata uses the same directory fields.

Every utterance carries its actual timestamp and source-derived order; CURRENT is newer than all included priors. Native edit event IDs stay separately bound. Root is an old anchor, and the root+seven window may omit middle messages. Newer clear human same-topic handoffs supersede older assignments only for that scope; historical proposals/assignments remain evidence, not executable approvals. A correction can address a preceding proposal's author without addressing somebody named as its repair object. Chronology and people data add no role/approval/confidence gate.

Discovery is limited to one GatewayRunner. It does not discover agents in other
processes or on other hosts. A shared bot contributes one event-specific native
runtime, not one candidate per configured profile. A disconnected bot is not a
candidate. Unknown or ambiguous identity, duplicate bot ownership, or a topology
change during evaluation yields no ordinary work. There is no hidden all-agent
or receiver-only fallback. Native policy still decides whether each receiver may act;
a discovered peer is not proof of channel membership or delivery.

Eligible current text, bounded prior text, source authors and candidate Slack
identities are sent to `https://api.typesafe.ai/v1/systemone` using `jev-latest`.
Enable this plugin only where you are authorized to send that conversation to
TypeSafe. Slack read access is not external-processing consent. There is no plugin
privacy classifier or per-channel egress-policy setting. Missing serving-profile
credentials or invalid responses result in no ordinary work. Production does not
log keys, transcripts or service error bodies, or store routing decisions.

## Behavior and limits

- Jev returns coherent `response` and speculative conditional exact `scope` for the
  bound receiver, judged with full oldest-to-newest conversation records and exact whoami context.
  Only response consumes confidence>.5; scope has no confidence threshold. Pure unsolicited
  courtesy/data/quoted commands do not independently request a response, whereas
  necessary support of one addressed request may belong. Exact source-owned `source_selection.segments.uN.text` is supplied
  with unchanged Unicode spans. Whoami separates user_id, username, display_name
  and supplementary real_name. Validated same-team/user/bot `users.info` supplies
  these fields; only the native authenticated bot username is a cache fallback.
  Empty display_name remains empty; unavailable fields are null, never synthesized
  from persona/runtime names or a real-name fallback. Native labels remain bound
  for historical provenance but runtime profile tags are not semantic self identity.
  Natural names, subject, root, handoff and joint intent remain Jev judgments;
  An eligible correctly addressed bot may participate in a joint request with human,
  context-only or outside co-assignees. Preserve its complete own joint source;
  never invoke outsiders or claim their receipt/consent/execution. Native self-auth
  stays mandatory. Classifier FN and extra triggers are reported separately from
  hard source/native invariants; the gate is not a promise of semantic perfection.
  code assembles exact native IDs/spans only. Optional inert-prior Choices cannot
  select recipients and retain include only at native confidence >=0.8. Every
  answer, including dormant speculative scope and unused priors, is structurally validated before
  consumption. Unknown question families reject. Native confidence is never p(YES).
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
  at most50 questions (one response, one conditional scope and48 optional priors; scope has up to63 nonempty source groups plus unsafe). Up to eight distinct prior records have 6,000 characters each
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
