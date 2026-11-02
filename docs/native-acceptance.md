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

Use an isolated official Hermes v0.22.5 checkout at
`bf0203a794a07aac3ff764972ab9087baa4e4f4e` for native integration. Replace the source
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
Inspect reported skips: the separate installed-wheel and native Git-installation
checks are not evidence of executed integration. The startup receiver is exercised
by its subprocess parent. The controlled suite does not call the live TypeSafe
service or read private recordings.

## What the checks establish

Core tests exercise exact Unicode source/provenance, same-context receiver
isolation, whole-message admission at 0.499/0.500/0.501, confidence independent of
probability, low-confidence scope without a second veto, optional priors and
malformed dormant answers. Controlled HTTP tests exercise the official request
shape, request-local credentials, serialized request/response bounds, safe errors,
no elapsed cutoff and resource closure on cancellation.

Native tests use real Bolt dispatch, SlackAdapter listeners, native source and
identity builders, authorization, mention/wake predicates and pending controls.
SDK I/O, semantic answers and final model/busy receivers are controlled. The suite
covers connected/foreign/duplicate/unserved participants, topology changes,
transport-versus-runtime secret scope, exact root/latest-seven acquisition,
short-tail cursor fill, projected-CURRENT admission, backfill/forgery isolation,
queue/merge/FIFO/replay, true-edit cancellation and cooperative native shutdown.
Positive paths must deliver nonempty exact scoped input alongside negative
security controls. Complete native presentation is formatted from independently
specified own CURRENT plus validated references; formatting CURRENT alone is not
a valid prefix oracle when appended references make trailing whitespace internal.

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
