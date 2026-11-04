# Hermes Slack Agent Router

Context-aware Slack routing for Hermes, powered by Jev. A transparent whole-message
filter implements `fallback-to-respond`: each receiving native identity asks one
yes/no intent question about the complete current message. Only a valid NO with
selected-answer native confidence strictly greater than 0.5 suppresses delivery.
NO requires positive grounds excluding this exact receiver from every fresh
response. Unknown or ambiguous addressing, leadership or assignment alone means
fallback YES/native continuation, not proven ownership or joint intent.
Every other result or plugin failure defers to ordinary native handling with the
original event unchanged. Passing is not execution permission or a guaranteed reply.

## Install and use

Requires Python 3.11+, a working Hermes Slack integration, and the qualified official
Hermes revision `f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab`. This plugin uses private
native seams; other host revisions require explicit integration testing. Earlier
qualification at `bf0203a794a07aac3ff764972ab9087baa4e4f4e` is historical, not proof
of the current native path.

Install through the native plugin manager. Replace `REVIEWED_COMMIT_SHA` with a
reviewed full 40-character plugin commit, not a branch or tag:

```sh
hermes plugins install https://github.com/u1-liquid/hermes-slack-agent-router.git --ref REVIEWED_COMMIT_SHA --yes-deps --no-enable
hermes plugins enable slack-agent-router --no-allow-tool-override
hermes plugins list
hermes plugins doctor slack-agent-router --ci
```

Enable only for profiles where external processing is authorized. Supply
`TYPESAFE_API_KEY` through normal Hermes secret setup in the runtime serving the
request, which may differ from the receiving transport profile. Do not inject
dependencies into a plugin-manager-selected environment with pip or uv.

There is no plugin configuration, manual participant/policy registry, assignment
database, thread-owner setup, Jev executable or TypeSafe SDK. Participants come
from the current GatewayRunner's connected authenticated Slack adapters. The
distribution is `hermes-slack-agent-router`, Python package
`hermes_slack_agent_router`, and plugin ID `slack-agent-router`.

If Atlas and Birch are both addressed in a mixed message, each nonexcluded bot
receives that same complete message, including the other bot's topic. The plugin
does not isolate foreign tasks by deleting text. General continuation may stay
with an evidenced lead; specific-task ownership, real handoffs, native @ addressing,
ambiguous names and joint participation remain part of whole-message intent.

Plugin Doctor verifies registration, not socket readiness or delivery. On the
qualified host, same-client disable/re-enable is not a supported hot replacement:
native factory deduplication may prevent attachment of a new callback. Use the
normal managed Gateway lifecycle for replacement activation.

## External processing and permissions

Eligible complete text and supported structured Slack blocks, bounded history and
whitelisted participant metadata go to `https://api.typesafe.ai/v1/systemone` with
`jev-latest`. Slack read permission is not external-processing consent. There is
no plugin privacy classifier or per-channel egress configuration.

Definitive native authorization and channel/mention eligibility precede classifier
egress. Commands, bots/self, DMs/MPIMs and pending approval, clarification,
confirmation or update controls keep their native path. Pass-through does not
override any native gate, force a mention, call the model directly or grant action
authority. Native history, media, sessions, pending queues and deduplication remain
host-owned, including when classification fails.

Credentials resolve per request in the serving runtime's native secret scope.
TLS verification is enabled; redirects, environment proxies and automatic Jev
retries are disabled. HTTP uses `timeout=None`, with no plugin elapsed cutoff on
inference/history/metadata. Diagnostics contain fixed codes and numeric measurements,
not transcripts, keys or service error bodies. Routing decisions are not persisted.

## Behavior and bounds

- One complete-CURRENT `response` question per receiver, including quoted/code-only
  messages. No paragraph/sentence/punctuation splitting, source subsets, partial
  extraction, regrouping, unit-count refusal or compatibility mode.
- Suppress only valid `response == "no"` with native confidence `> 0.5`. YES at any
  confidence and NO at/below 0.5 pass. Class probability is validated protocol data,
  never the suppression threshold. Missing, malformed or contradictory answers pass.
  Duplicate JSON members (including escaped equivalents and nested probability
  keys) are rejected before decoding can collapse contradictory values.
- History, metadata, topology, credentials, transport, HTTP, encoding, schema,
  semantic preparation and size failures pass the original event natively. Unsupported
  media/composition skips inference rather than classifying only a text fallback.
- Replies use verified root plus latest seven strictly prior records, within four
  SDK calls and 1 MiB per decoded response. Newest-window endpoint selection is a
  qualified integration assumption, not a universal Slack ordering guarantee.
- Top-level messages support absent, null or explicit self-root `thread_ts`.
  Conversation root and each adapter's native session coordinates are separate.
  CURRENT==root is one protected record and never fetches its own prior thread.
- Up to four native recipients and 13 contextual people bound metadata acquisition,
  not text segmentation. Actual compact UTF-8 requests are capped at 524,288 bytes;
  fitting removes only whole oldest non-root priors and unused people. ROOT and
  CURRENT are never shortened. Protected-only excess passes locally without HTTP.
  Responses are separately capped at 262,144 bytes.
- True newer edits invalidate and drain obsolete active evaluation; stale active
  revisions cannot hand off. Equal duplicates and later distinct messages do not
  cancel it. Caller cancellation and Gateway shutdown are terminal, not fallbacks
  that resurrect an event. This cannot retract already handed-off work.
- Disabled/unloaded filters defer live events to native handling, even when unload
  occurs during acquisition/inference. Unload is not Gateway shutdown. Actual
  caller/edit/shutdown cancellation remains authoritative.

Discovery is local to one GatewayRunner, not other processes/hosts. Unavailable or
ambiguous topology causes native pass-through, never inference for a guessed
receiver. There is no durable owner, atomic history snapshot, cross-process
consensus or exactly-once guarantee. Semantic confidence guarantees neither
another participant's receipt nor native response/model execution.

## Troubleshooting and disabling

Check the native Slack connection, serving runtime, scoped key and root/recent
context. Fixed diagnostics distinguish acquisition, topology and classifier
failures. Resolve access through the existing Slack integration, not borrowed
tokens. Do not paste credentials/private input into logs. Classification failure
alone does not explain silence: native gates and lifecycle may still exclude work.

```sh
hermes plugins disable slack-agent-router
hermes plugins remove slack-agent-router
```

## Development

See [design](docs/design.md) and [testing](docs/native-acceptance.md). CI has separate
`core` and `native` jobs on Python 3.14. Controlled tests are not live Slack delivery,
real classifier accuracy, independent review or deployment acceptance.

MIT license, copyright u1-liquid.