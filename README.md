# Hermes Slack Thread Assignee

Contextual Slack routing for Hermes. Jev identifies which earlier message, person
and topic each current instruction addresses. Each eligible agent receives only
its own actionable CURRENT spans and selected, explicitly inert PRIOR references.
A message can address several agents with different work.

## Install and use

Requires Python 3.11+, Hermes v0.22.5 at
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`, and its working Slack integration.
The native integration uses private host seams and is tested against that exact
revision. Package metadata alone does not establish compatibility with other hosts.

Install into the same Python environment that runs Hermes:

```sh
python -m pip install 'git+https://github.com/u1-liquid/hermes-slack-thread-assignee.git@feat/stable-thread-assignee'
hermes plugins enable slack-thread-assignee
hermes plugins doctor slack-thread-assignee --ci
```

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
- Replies need the root and a complete short history: at most six prior messages
  and 6,000 prior characters. Pagination, missing roots and foreign/future/conflicting
  records are unresolved, not silently truncated.
- Current input is limited to 6,000 characters, six units, four recipients and
  96 questions. Request and response bodies are each limited to 262,144 bytes.
  Media and inseparable authored/reference composition are unsupported.
- The ingress budget is 2.5 seconds, including context and the at-most-1.2-second
  Jev request. These are engineering deadlines, not hard real-time guarantees.
  TLS is verified; redirects, environment proxies and automatic retries are disabled.
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
served profile, serving-profile key and complete short history. Local codes such as
`incomplete-context`, `native-topology-unresolved`, `native-topology-changed`, `classifier-failed` and
`coverage-or-grounding-unresolved` distinguish bounded failures. `ingress-failed`
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
hermes plugins disable slack-thread-assignee
python -m pip uninstall hermes-slack-thread-assignee
```

## Development and verification

See [design](docs/design.md) for data flow and native boundaries and
[testing](docs/native-acceptance.md) for runnable offline and opt-in fictional tests.
CI has distinct `core` and `native` jobs, both on Python 3.14. Offline tests require
no real TypeSafe key. Passing controlled tests is not a live Slack deployment check
or a guarantee of classifier accuracy.

MIT license, copyright u1-liquid.
