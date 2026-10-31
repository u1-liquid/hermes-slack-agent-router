# Hermes Slack Agent Router — testing

## Offline repository checks

Run from the repository root with Python 3.14, the CI interpreter:

```sh
python -m pip install . ruff==0.17.3 build
python -W error::ResourceWarning -m unittest discover -s tests -p test_core.py -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_semantic.py -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_boundaries.py -v
ruff check __init__.py hermes_slack_agent_router tests
ruff format --check __init__.py hermes_slack_agent_router tests
python -m build
```

Core startup also invokes a fresh `-S` subprocess without optional host SDKs.
It needs no plugin config file or bootstrap. Semantic tests exercise exact source
spans, selected prior authors, topic groups, joint recipients, generic continuation,
multilingual acknowledgement/new-work separation, atomic uncertainty and typed
confidence. Controlled HTTP tests check official URL/authentication, missing-key
no-egress, body caps, faults and async cancellation/resource closure.
Root/recent tests cover root outside the latest seven, ascending old-first cursor
pages, pinned cutoff/current exclusion, overlap/dedup, edits/field provenance,
malformed/foreign/missing/failed retrieval, bounds, fallback and explicit handoff
precedence. Incomplete retrieval never becomes semantically unhelpful context.
Source-local proof tests cover historical joint sets, recent topic-only context
with a root assignee, swapped users with identical runtime names, plain assignment
conflicts versus explicit takeovers, disputes/unsafe facts and current partial-outside
joint rejection. Every relevant positive and negative fact/link/address decision
retains the same confidence gate; controlled facts are not real-model evidence.

## Complete newly assembled input

The native `pre_gateway_dispatch` hook consumes a request-local Python closure
attached only after successful ordinary-message projection. Slack JSON cannot
construct that closure. It rechecks the native sender, source/message, recipient,
serving runtime and runner before removing newly hydrated `channel_context`,
reply backfill and recovered root media. The witness is removed before native
admission/persistence; there is no registry or persisted routing representation.
Selected inert prior references remain in projected text. Existing native session
memory, channel configuration, authorization, controls and exempt events are not
cleared or replaced. A changed binding skips the routed request, rather than
passing unscoped backfill.

Native regressions inspect the complete event and actual sender/context prefix,
with nonempty cold-thread and active explicit-mention fetches, selected and
superseded prior, nonrecipient exclusion, native queue/merge/replay, cross-profile
serving context, JSON forgery/binding negatives and the native persistence codec.
These are controlled SDK/semantic tests, not fresh external inference or live Slack.

## Native integration

Use a separate official checkout at the pinned revision, never an installed/live
Hermes home. `HERMES_TEST_SOURCE` must be an absolute path to that checkout.
Install the test dependencies in an isolated environment:

```sh
python -m pip install -r tests/requirements-native.txt . build
export HERMES_TEST_SOURCE=/absolute/path/to/isolated/hermes-agent
export HERMES_REQUIRE_NATIVE=1
python -W error::ResourceWarning -m unittest discover -s tests -p test_native.py -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_plugin_surface.py -v
```

The target is Hermes v0.22.5, commit
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`. Tests isolate fixture homes and use
actual Slack Bolt AsyncApp dispatch, SlackAdapter listeners, source/canonical
identity builders, native transport maps and authority registry. Slack network I/O,
socket observations and final model/busy receivers are controlled. Offline Jev
answers are controlled too; these tests are not a live Slack or real inference test.

Assertions cover discovered multi-transport candidates, receiver-independent
canonical inputs and recipient-specific received text. They also cover lost,
foreign, ambiguous and changing topology, source grounding, original/projected
native admission, pending controls, normal/busy/shared-burst/queue/merge/replay,
empty acknowledgements and no model/warning/queue effects on rejected input.
Native secret-scope tests distinguish the serving runtime from receiving context
and verify missing-scope and concurrent multiplex isolation.

`test_plugin_surface.py` separately exercises real directory discovery,
registration, factory activation with no configuration and Plugin Doctor.
`test_installed.py` must run against a freshly built wheel installed into an empty
separate target, outside the source checkout:

```sh
python -m build
python -m pip install --target /absolute/path/to/empty-wheel-target dist/*.whl
export HERMES_WHEEL_TARGET=/absolute/path/to/empty-wheel-target
export HERMES_DIST_DIR=/absolute/path/to/repository/dist
export HERMES_REQUIRE_WHEEL=1
cd /absolute/path/outside/source
python -I -W error::ResourceWarning -m unittest discover -s /absolute/path/to/repository/tests -p test_installed.py -v
```

A source-suite wheel skip is not installed-package proof. CI's distinct `native`
job requires native setup and the outside-checkout installed-wheel test; `core`
requires deterministic suites, formatting, lint and build. Both use Python 3.14.

## Opt-in fictional API tests

Only use wholly fictional or explicitly public-permitted fixtures. Do not send
private/customer/credential content or reversible derivatives. Use the caller's
existing native Hermes `TYPESAFE_API_KEY` scope; do not put real keys in test homes
or protocol artifacts. Offline CI does not run these tests or need a real key.

```sh
export JEV_FICTIONAL_CANARY_DIR=/absolute/path/to/private/fictional-evidence
python -W error::ResourceWarning -m unittest discover -s tests -p test_semantic.py -k real_fictional -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_native.py -k real_jev -v
```

The native test also requires the isolated host setup above. The recording harness
preserves fictional request/result/plan and received-input evidence; production
writes none of those files. SDK history and final model receivers remain controlled
while Jev inference uses the actual official HTTPS client.
To run only the changed root/recent native examples, use `-k real_jev_root` with
that native command. They exercise a human-authored root outside seven recent
messages, generic/topic root fallback, newer general-lead/topic handoff priority
and actual native received input. Slack SDK history and final model remain controlled.
For an authorized changed-protocol qualification against retained recordings, set
`JEV_SAME_INPUTS_DIR` to the original four-case evidence directory. The recording
harness checks exact original input-state equality, excluding only removed internal
precedence instructions, before contacting Jev. Use a fresh output directory;
never overwrite or relabel an earlier failed recording.

A confidence abstention is a no-work result, not successful delivery. Preserve
failed assertions and inspect their actual source/answers; do not lower thresholds
or retry an unchanged request solely to manufacture green. These examples measure
bounded behavior, not calibrated classifier accuracy or deployment readiness.

To check an existing fictional native recording against changed source without
another HTTP request, set `JEV_RECORDED_CANARY_DIR` to its evidence root and run
`test_native.py -k recorded_jev` with the same unittest discovery command. This
requires exact equality with each saved request, validates its typed response,
executes native scoped delivery and compares the received text. It does not modify
the recordings or establish a fresh external-service result.

For a source-local four-case recording, set `JEV_SOURCE_LOCAL_RECORDED_DIR` and run
`test_semantic.py -k recorded_source_local`. This checks exact generated requests,
validates typed answers and compares assembled text with the saved native input.
Every case must have a qualified ready plan and nonempty matching saved delivery.
Recorded confidence abstentions remain failed deliveries, not passing bridge cases;
older protocol recordings require their matching historical source for exact replay.

## Operational boundaries

These tests do not install into a live gateway, process private Slack, restart a
gateway or change production credentials. Discovery is runner-local, not a remote
participant directory. Native socket observations and request-local revalidation
are not a global topology transaction. Same-client unload/re-enable needs separate
lifecycle handling because native factory deduplication can prevent replacement
attachment. See [runtime design](design.md) for the supported boundaries.
