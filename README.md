# Hermes Slack Thread Assignee

Stateless contextual Slack routing for Hermes. Bounded native conversation evidence
and one typed Jev question batch determine which message/person/topic each instruction
addresses. Each eligible recipient gets only its own CURRENT source spans and selected,
explicitly non-actionable PRIOR references. One message can address several recipients
with different work, or several people on the same topic.

There is no assignment database, plugin transcript/decision/topic store, initialization,
manual main-owner bootstrap, management CLI, migration or recovery service. The plugin
holds only request-local values. It does not replace persistence with JSON/Redis/files.
Native Hermes/Slack retain their own history, session, queue and dedup responsibilities.

## Installation and activation

This is an unmerged feature candidate, not a live deployment or PyPI release. Python
3.11+ is supported by package metadata; CI runs the distinct core/native gates on3.14.
Install in the same environment as Hermes, selecting the explicit candidate branch:

```sh
python -m pip install 'git+https://github.com/u1-liquid/hermes-slack-thread-assignee.git@feat/stable-thread-assignee'
hermes plugins enable slack-thread-assignee
```

The package supplies the official `hermes_agent.plugins` entry point and directory
`plugin.yaml`. The native plugin installer does not accept arbitrary local package
directories. Copy `examples/config.json`, replace the fictional participant identities
and input-policy scope, and set `HERMES_THREAD_ASSIGNEE_CONFIG` to its absolute path in
the gateway launch environment. No DB directory or init command is required. The config
is static participant/input policy, not a routing-state file. Use the same participant
registry and permitted conversation view for all agents; bot→runtime mappings must be
unambiguous within each workspace. Participants are ordered canonically, never by the
currently receiving agent. Missing/invalid config reports failed activation; discovery
and Plugin Doctor alone do not prove active routing or delivery.

Disable with `hermes plugins disable slack-thread-assignee`. Retained callbacks become
pass-through; physical callback unwiring is unavailable, so replacement/re-enable needs
an operator-managed gateway restart. This documentation does not authorize a restart.
Uninstall the distribution with `python -m pip uninstall hermes-slack-thread-assignee`;
directory plugins use `hermes plugins remove slack-thread-assignee`. No data deletion
or migration is performed, including deletion of any historical database from an older
unreleased candidate.

## Input policy and real Jev

Semantic egress is disabled by default. The example permits ONLY fictional content in
one fictional workspace/channel. A configured scope asserts authorization for the entire
bounded current/history/identity input and its audience, not merely Slack read access.
Only `fictional` and `public-permitted` data classes are supported. A public channel name,
hash or alias is not permission to send private/customer/credential data. Do not deploy
this candidate on private conversations using the example policy.

Jev CLI0.23.1 must be available on PATH and authenticated through its documented
`TYPESAFE_API_KEY` environment or native keystore interface. The plugin embeds/copies no
credentials. It runs actual `jev ask --timeout` with a named typed Choice batch and
validates exact answer keys, types, finite probabilities, coverage, source grounding and
confidence0.8 for relevant judgments. No model-generated instructions or identifiers are
accepted. People derive from selected source-message authors; topics are request-local
groups, not permanently assigned IDs.

A generic continuation can reach a uniquely inferred conversational lead supported by
native history in the same Jev batch. That is not permanent ownership or permission.
A secondary invitation does not automatically transfer the general conversation. Specific
work does not require a known general lead. Missing/ambiguous lead, incomplete partition,
conflicting evidence or any failed actionable unit makes the WHOLE message unresolved;
no partial instruction is quietly omitted and no all-agent fallback is used.

Unresolved ordinary input gets empty transport200 and fixed bounded local diagnostics
such as `privacy-disabled`, `incomplete-context`, `classifier-failed` or
`coverage-or-grounding-unresolved`. It does not invoke the main model, steer/queue work
or post a silence warning. No durable unresolved queue, inspection/replay command or
operator cache exists. Retrying is native transport behavior, not plugin recovery.

## Native safety and supported bounds

The plugin uses the public platform factory/global Bolt middleware and a deep private
`req.body` projection before native listener/busy processing. Envelope identity and original
provenance are preserved. Only assigned CURRENT composition survives; selected PRIOR
references are labeled and their mentions rendered non-wake-bearing. Unsupported media,
root files and inseparable authored/reference composition are explicit unresolved.

Original AND projected native admission must permit. Classifier output never grants
sender/channel/mention/wake permission or broadens a short approval. No fake mention,
force flag, Slack post, core monkeypatch, provider rewrite or transcript surgery is used.
Commands, DMs/MPIMs, bots/self and exact monitoring exemptions retain native handling.
Pending approval/clarification/confirmation/update state is rechecked after awaits,
including failures. Unknown identity/control mapping remains qualified native pass-through;
a disabled/broken plugin is not a universal fail-closed enforcement boundary.

Context is deliberately bounded to a complete short thread: root required for replies,
at most6 prior messages/6000 prior characters, with the triggering current timestamp
excluded. History pagination/has_more, missing root, foreign/future/conflicting records
or unsupported prior composition are unresolved rather than silently truncated. Canonical
ordering uses original source IDs and sorted scoped recipients, not local agent preference.
Current text is at most6000characters,6 units,4 recipients and96 questions. Serialized
request/stdout are capped at262144bytes, stderr at16384. Whole ingress target2.5s includes
context and Jev (at most1.2s); cancellation kills/reaps request inference. This is not a
hard real-time scheduling SLA.

Normal input, legacy busy/steer, shared burst, runner FIFO/merge/replay and pending controls
are exercised at pinned native boundaries. Native duplicate accepted-event suppression
is retained, but separate ingress events/processes/restarts may classify again and may
receive different stochastic results. Identical canonical inputs are not a cross-process
consensus or exactly-once guarantee. Restart reconstructs context through the native
history boundary, with no plugin-state restoration or manual owner setup.

## Verification

CI has one Python3.14 `core` job (deterministic tests, Ruff, build) and a distinct required
Python3.14 `native` job (pinned host, native dispatch, discovery/Doctor and freshly rebuilt
wheel installed outside source). No external Jev credentials are used in CI.

Local real canaries require wholly fictional/public-permitted fixtures and explicit
`JEV_FICTIONAL_CANARY_DIR`. Select `test_real_fictional_semantic_journeys` in
`tests/test_semantic.py` and `test_real_jev_contextual_generic_and_multitopic_native_inputs`
in `tests/test_native.py` (the latter also needs `HERMES_TEST_SOURCE`). Raw protocol evidence
is written ONLY by the opt-in test harness, never the production client. Controlled SDK
I/O/final model receivers are distinct from actual external Jev inference. Passing these
bounded cases is not calibrated classifier accuracy, private-input authorization or a
live Slack/deployment check. See [design](docs/design.md), [implementation plan](docs/implementation-plan.md)
and [native acceptance](docs/native-acceptance.md).

MIT license, copyright u1-liquid.
