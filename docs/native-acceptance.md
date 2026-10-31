# Testing

## Offline repository checks

Run from the repository root with Python 3.14, the CI interpreter:

```sh
python -m pip install . ruff==0.17.3 build
python -W error::ResourceWarning -m unittest discover -s tests -p test_core.py -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_semantic.py -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_boundaries.py -v
ruff check hermes_slack_thread_assignee tests
ruff format --check hermes_slack_thread_assignee tests
python -m build
```

Core startup also invokes a fresh `-S` subprocess without optional host SDKs.
It needs no plugin config file or bootstrap. Semantic tests exercise exact source
spans, selected prior authors, topic groups, joint recipients, generic continuation,
multilingual acknowledgement/new-work separation, atomic uncertainty and typed
confidence. Controlled HTTP tests check official URL/authentication, missing-key
no-egress, body caps, faults and async cancellation/resource closure.

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

A confidence abstention is a no-work result, not successful delivery. Preserve
failed assertions and inspect their actual source/answers; do not lower thresholds
or retry an unchanged request solely to manufacture green. These examples measure
bounded behavior, not calibrated classifier accuracy or deployment readiness.

## Operational boundaries

These tests do not install into a live gateway, process private Slack, restart a
gateway or change production credentials. Discovery is runner-local, not a remote
participant directory. Native socket observations and request-local revalidation
are not a global topology transaction. Same-client unload/re-enable needs separate
lifecycle handling because native factory deduplication can prevent replacement
attachment. See [runtime design](design.md) for the supported boundaries.
