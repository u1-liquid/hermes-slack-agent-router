# Hermes Slack Agent Router

Context-aware Slack routing for Hermes, powered by Jev. Each receiving bot judges
whether the complete current message asks it to respond, then receives only its
exact source text and selected inert references. One message can address several
bots with different work. Routing does not authorize external actions.

## Install and use

Requires Python 3.11+, a working Hermes Slack integration, and Hermes v0.22.5 at
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`. The plugin uses private native seams;
other host revisions need explicit integration testing.

Install through the native plugin manager. Replace `REVIEWED_COMMIT_SHA` with a
reviewed full 40-character commit, not a branch or tag:

```sh
hermes plugins install https://github.com/u1-liquid/hermes-slack-agent-router.git --ref REVIEWED_COMMIT_SHA --yes-deps --no-enable
hermes plugins enable slack-agent-router --no-allow-tool-override
hermes plugins list
hermes plugins doctor slack-agent-router --ci
```

Enable the plugin for each receiving profile that needs selective routing. Use
Hermes's normal secret setup to supply `TYPESAFE_API_KEY` in the runtime that
serves requests. That runtime can differ from the receiving bot's profile. Do not
inject dependencies into a plugin-manager-selected environment with pip or uv.

There is no plugin configuration file, manual participant/policy registry,
assignment database, initialization command or thread-owner setup. Participants
come from the gateway's connected, authenticated Slack adapters. No Jev executable
or TypeSafe SDK is required. The distribution is `hermes-slack-agent-router`, the
Python package is `hermes_slack_agent_router`, and the sole plugin ID is
`slack-agent-router`.

For example, if history establishes that Atlas prepared a summary and Birch
prepared a diagram, “Atlas, revise the summary; Birch, check the diagram” can
produce different inputs for the two bots. A general continuation can stay with
an evidenced conversational lead, including a bare no-@ name call. Specific-topic
assignments, genuine handoffs and native @ addressing remain distinct; the plugin
does not invent a lead or reply to everyone.

Plugin Doctor checks registration, not socket readiness or delivery. Use the
normal managed gateway lifecycle when activating a replacement. On the pinned
host, same-client disable/re-enable is not a supported hot replacement because
native factory deduplication can prevent a new callback from attaching.

## External processing and activation boundary

Enable this plugin only where you are authorized to send the conversation to
TypeSafe. Eligible current text, bounded prior text, author metadata and candidate
Slack identities go to `https://api.typesafe.ai/v1/systemone` with `jev-latest`.
Slack read permission alone is not external-processing consent. There is no
plugin privacy classifier or per-channel egress setting.

Credentials resolve inside the serving runtime's native secret scope. TLS is
verified; redirects, environment proxies and automatic Jev retries are disabled.
The router sets `httpx`'s `timeout=None` and imposes no elapsed-time cutoff on
inference, history or identity reads. Native transport policies remain native.
Missing credentials, external errors and invalid answers produce no ordinary work.
Production does not log keys, transcripts or service error bodies, or persist
routing decisions.

## Routing behavior and limits

- One whole-message `response` decision admits only YES with native confidence
  strictly greater than 0.5. Probability is not confidence. Conditional `scope`
  selects the complete exact own-source extent without another confidence,
  approval or executable-work gate. Questions, explanations, requested
  acknowledgements and necessary supporting clauses can qualify.
- Source slices are extraction choices, not fragment response ballots. An
  unrepresentable own extent is `projection-unresolved`, not semantic NO or a
  fallback to the whole mixed message. Optional prior references require native
  confidence at least 0.8 and never select recipients or veto admission.
- An eligible bot may respond to a joint request with human or outside
  co-assignees. It does not invoke outsiders or claim their consent or execution.
- Acquisition keeps the verified root and latest seven strictly prior replies.
  It follows older cursors only to fill a short tail, within four SDK calls and
  1 MiB per decoded response. The pinned endpoint's newest-page selection is a
  qualified integration assumption, not a universal Slack ordering guarantee.
- Current text has at most six source segments, with at most four native recipients
  and 50 questions. The actual serialized request is limited to 524,288 UTF-8 bytes.
  Fitting drops whole oldest non-root priors and regenerates the request; full
  CURRENT and ROOT are protected. Protected-only excess stops locally without HTTP.
  The separate response limit is 262,144 bytes. Unsupported media and inseparable
  authored/reference composition are rejected, not replaced by notification text.
- Native authorization precedes private inference. Original and projected CURRENT
  use the native channel/mention/wake predicates. Commands, bots/self, DMs/MPIMs and
  pending controls keep native handling. Unselected ordinary input is acknowledged
  silently before model, queue or steering work.
- Explicit newer source edits invalidate and drain obsolete active evaluation;
  equal duplicates and later distinct messages do not cancel it. Native shutdown
  owns cooperative task draining. This cannot retract already queued/running work.

Discovery is local to one GatewayRunner, not other processes or hosts. Ambiguous,
disconnected, foreign or unserved identities do not become fallback recipients.
Native history, sessions, queues and deduplication remain host-owned. Separate
events can classify differently; there is no durable owner, cross-process consensus
or exactly-once guarantee. Slack history is not an atomic snapshot. Disabling or
breaking this plugin is not a universal fail-closed enforcement boundary.

## Troubleshooting and disabling

Check the Slack connection, serving runtime, runtime-scoped key and supported
root/recent source first. Fixed payload-free diagnostics distinguish topology,
context acquisition, classifier and source-projection failures. Access failures
must be resolved through the existing Slack integration, not borrowed tokens or
a plugin credential store. Do not paste private input or credentials into logs.

```sh
hermes plugins disable slack-agent-router
hermes plugins remove slack-agent-router
```

## Development

See [design](docs/design.md) for data flow and trust boundaries and
[testing](docs/native-acceptance.md) for controlled checks. CI has separate `core`
and `native` jobs on Python 3.14. Controlled tests do not establish live Slack
delivery, classifier accuracy or deployment acceptance.

MIT license, copyright u1-liquid.
