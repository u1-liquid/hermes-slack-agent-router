# Testing

## Controlled checks

CI uses Python 3.14 with separate `core` and required `native` jobs. Use an existing
prepared environment with the declared project/test dependencies. Do not install
into a managed plugin environment or run these checks against a live Hermes home.
No real TypeSafe key is needed for the controlled suite.

Core checks from the repository root:

```sh
python -W error::ResourceWarning -m unittest discover -s tests -p test_core.py -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_semantic.py -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_simple.py -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_boundaries.py -v
ruff check __init__.py hermes_slack_agent_router tests
ruff format --check __init__.py hermes_slack_agent_router tests
```

Use an isolated official Hermes checkout at
`f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab` for native integration. Replace the source
path below with that prepared checkout. `HERMES_REQUIRE_NATIVE=1` makes missing
native setup fail rather than silently skip.

```sh
export HERMES_TEST_SOURCE=/absolute/path/to/isolated/hermes-agent
export HERMES_REQUIRE_NATIVE=1
python -W error::ResourceWarning -m unittest discover -s tests -p test_native.py -v
python -W error::ResourceWarning -m unittest discover -s tests -p test_plugin_surface.py -v
```

To run every controlled test with that native setup:

```sh
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v
```

Set `TMPDIR` to a task-owned temporary directory if the default is unsuitable.
Inspect reported skips: skipped installed-wheel checks are not evidence of
executed integration. The startup receiver is exercised
by its subprocess parent. The controlled suite does not call the live TypeSafe
service or read private recordings.

## What the checks establish

Core tests exercise complete Unicode text and structured quote/code content,
same-context receiver identity, native selected confidence independent of class
probability, ties, malformed complete answers and exact UTF-8 fitting. Raw duplicate
JSON members at envelope/answer/probability levels, including escaped-equivalent
keys, must defer once with payload-free diagnostics and closed HTTP resources;
valid YES/high-NO and normal envelope metadata remain controls.
Controlled HTTP tests exercise the official request
shape, request-local credentials, serialized request/response bounds, safe errors,
no elapsed cutoff and resource closure on cancellation.

Native tests use real Bolt dispatch, SlackAdapter listeners, native source and
identity builders, authorization, mention/wake predicates and pending controls.
SDK I/O, semantic answers and final model/busy receivers are controlled. The suite
covers connected/foreign/duplicate/unserved participants, topology changes,
transport-versus-runtime secret scope, exact root/latest-seven acquisition,
short-tail cursor fill, absent/null/self-root/reply thread coordinates with unequal
peer settings, complete original payload/history preservation, busy/queue/merge/FIFO/replay,
true-edit/caller/shutdown cancellation and in-flight unload pass-through. The
fallback-to-respond rule suppresses only valid NO with native confidence >0.5;
YES at any confidence, NO<=0.5 and plugin failures defer unchanged to native.
Compare exact original handoff independently of ordinary native formatting and
mention humanization. Native authorization/channel/mention/bot/pending gates remain
authoritative; plugin pass-through does not guarantee a model response.

The independently fictional 103 conversational inputs retain declared whole-message
continuation decisions. Unresolved main-unknown/main-conflict/M9, the matching
normal-name cases and both C-unresolved receivers expect fallback YES, not proven
ownership or semantic accuracy. Demonstrably foreign and inert/courtesy/data
negatives remain. The outgoing one-question rubric is audited through controlled
HTTP separately from the injected decisions. Partial-CURRENT masks, projection/backfill restrictions and
scope/prior-selector assertions are retired as user-superseded, not relabelled PASS.
There is no compatibility fixture schema for the removed architecture.

Passing these tests proves controlled protocol and native-boundary behavior, not
classifier accuracy, genuine Slack delivery or deployment acceptance. Request
recording, model observations, independent review and runtime adoption are separate
claims. Classifier false negatives and extra triggers must remain disclosed;
model quality does not replace hard authorization/source-isolation requirements.

## Packaging and native plugin surface

`test_plugin_surface.py` checks real directory discovery, registration, factory
attachment and Plugin Doctor without plugin configuration or a database. A skipped
wheel test does not establish packaged imports or archive contents.

In an authorized build environment:

```sh
python -m build --no-isolation
```

CI stages the resulting wheel in a separate empty target, outside managed homes.
With a prepared target and fresh distribution directory, run the installed-package
checks outside the source checkout:

```sh
export HERMES_WHEEL_TARGET=/absolute/path/to/empty-wheel-target
export HERMES_DIST_DIR=/absolute/path/to/fresh-dist
export HERMES_REQUIRE_WHEEL=1
python -I -W error::ResourceWarning -m unittest discover -s /absolute/path/to/repository/tests -p test_installed.py -v
```

These inspect wheel/sdist metadata and exercise the installed entry point through
the pinned native plugin manager. They do not authorize dependency changes, live
install/enable/restart, Slack posting, publication, merge or deployment.

## Documentation checks

Read [README](../README.md) and [design](design.md) against current source. With an
existing `markdown-it` CLI, render all three documents without executing examples:

```sh
markdown-it README.md docs/design.md docs/native-acceptance.md > /absolute/path/to/task-owned/docs.html
```

Inspect heading/list/code structure and relative link targets. Parsing is not
strict Markdown lint, runtime verification or standards certification. Historical
campaigns and failed candidates are recoverable from Git history and private task
receipts; they are not current installation instructions or acceptance authority.
