# Hermes Slack Thread Assignee

Contextual, multi-topic Slack assignment for Hermes. One shared Jev plan gives each
eligible recipient only its own CURRENT instructions and labeled PRIOR references.
Trusted local administration, never messages or Jev, establishes the thread main.

## Status and installation

This is a locally exercised semantic candidate, not a deployed gateway or a release
on main. Independent review and exact-head CI are required before release. Python
3.11+ and owner-only SQLite on one local host are engineering selections.

```sh
uv venv .venv
uv pip install --python .venv/bin/python .
.venv/bin/hermes-thread-assignee --help
```

For a published candidate use its explicit feature ref, not main:

```sh
python -m pip install 'git+https://github.com/u1-liquid/hermes-slack-thread-assignee.git@feat/stable-thread-assignee'
hermes plugins enable slack-thread-assignee
```

Install in the same environment as Hermes. The package provides the official
`hermes_agent.plugins` entry point and a directory `plugin.yaml`. The native plugin
installer does not accept arbitrary local package directories. Set the absolute
`HERMES_THREAD_ASSIGNEE_CONFIG` path in the gateway launch environment. Discovery,
registered CLI and Plugin Doctor do not prove active middleware or native delivery.
Without configuration native wiring reports an error rather than pretending healthy.

Disable with `hermes plugins disable slack-thread-assignee`. Disposed callbacks
pass through; re-enable/replacement needs an operator-managed gateway restart.
Uninstall an installed distribution using `python -m pip uninstall
hermes-slack-thread-assignee`; directory plugins use `hermes plugins remove
slack-thread-assignee`. These are instructions, not automated restart permission.
Neither removal nor disabling deletes the shared database.

## Configuration and privacy

Copy `examples/config.json`, replace the fictional registry and storage path, and
create the immediate parent directory owned by the operator with mode 0700. All
participants must share database path, identity and registry revision. Explicit
`init` creates mode-0600 storage and idempotently adds semantic tables to schema1;
runtime never initializes, resets or repairs missing/corrupt/mismatched storage.

Semantic egress is disabled by default. The example explicitly enables ONLY a
fictional workspace/channel and fictional data class. Setting a scope asserts the
operator has authorized the entire bounded current/history/identity input, not
merely that the bot can read Slack. A channel name, hash or alias is not evidence
that private content is safe. Only `fictional` and `public-permitted` classes are
supported; this candidate does not authorize private/customer/credential egress.
Do not deploy it on private conversations under the example policy.

With a configured policy, disabled or out-of-scope ordinary inputs are durable
`privacy-disabled` unresolved and cause no semantic history retrieval/Jev call or
agent turn. Unknown native controls/identity mapping remain native pass-through
with degraded coverage; routing is not an authorization replacement.

Jev CLI0.23.1 must be on PATH and authenticated through its documented environment
or keystore interface. No credentials are embedded or copied by the plugin. It
uses native `jev ask --timeout`, one shared typed Choice batch, not generated JSON
instructions. Confidence0.8 remains required for relevant action/reference/coverage
judgments. Recipient membership supports sets. People are the authors of selected
source messages, not a second contradictory single-person model choice.

## Administration, inspection and retention

```sh
hermes-thread-assignee --config /path/to/config.json init --dry-run
hermes-thread-assignee --config /path/to/config.json init
hermes-thread-assignee --config /path/to/config.json check
hermes-thread-assignee --config /path/to/config.json establish --workspace TDEMO --channel CDEMO --thread 100.001 --recipient alpha --if-absent
hermes-thread-assignee --config /path/to/config.json show --workspace TDEMO --channel CDEMO --thread 100.001
hermes-thread-assignee --config /path/to/config.json transfer --workspace TDEMO --channel CDEMO --thread 100.001 --recipient beta --expected-revision 1 --reason 'operator handoff' --dry-run
hermes-thread-assignee --config /path/to/config.json plans
```

`hermes thread-assignee` exposes the same parser. JSON errors exit nonzero. Main
transfer/clear require observed CAS revisions and reasons; clear retains a
revision tombstone. The OS account is trusted; no model-facing mutation tool or
Slack assignment command exists. Main and audit are independent of content expiry.

`plans` returns at most100 metadata rows, reason, fence/binding and native receipt
states, never source text. `may_have_more` identifies the bounded listing limit.
A projected/native receipt is NOT delivery, completed work or exactly-once execution.

Retention is explicit, not scheduled: bounded per-message content remains until
operator purge. Protect backups and database permissions. Example operation shape
(substitute the exact observed lowercase binding digest and fence):

```sh
hermes-thread-assignee --config /path/to/config.json purge --binding DIGEST --expected-fence 1 --quiescent --dry-run
hermes-thread-assignee --config /path/to/config.json recover --binding DIGEST --expected-fence 1 --quiescent --dry-run
```

Use `--apply` instead of `--dry-run` only after inspecting the preview and stopping
ALL consumers, queued/replayed inputs and admission. `--quiescent` is an operator
assertion, NOT a gateway lease or automatic proof. Active claims are refused even
with that assertion. Purge forgets the exact binding's retained snapshots/plans/
receipts, keeps an unresolved metadata tombstone and never deletes main/audit.
It is not forensic secure erasure of SQLite free pages, journals or backups.
Recovery only reopens retained unresolved work for a subsequent native retry;
it cannot replay Slack, bypass native policy or reclassify accepted/purged work.
Previously accepted generations remain immutable until explicit quiescent purge.

The bounded metadata listing includes archived bindings and fences, not only current
pointers. Exact archived purge leaves the current binding and main/audit unchanged;
retained tombstones prevent old retries from rehydrating forgotten payloads.
Definitive native sender denial is checked before semantic context/Jev. Configured
native wake patterns count only in original and assigned CURRENT text, never PRIOR.
Bootstrap prior-message IDs are not distinct semantic topics: validated joint refs
receive one stable source-message-scoped topic per validated CURRENT group; exact retained earlier reference links can
restore a known topic. Conflicting established topics remain unresolved.

## Execution and uncertainty boundaries

Ordinary rich_text is flattened with exact original leaves, canonical Unicode
half-open spans, raw scalar ranges and mapping kinds; structural separators do not
claim authored byte positions. Only assigned CURRENT spans survive in the private
request copy. Original envelopes and selected original prior references remain
separate; rendered references have non-wake-bearing mentions. Main is fallback
only for a positively grounded generic continuation. Quotes/code are reference;
inseparable mixed authored/reference candidates and unsupported media are unresolved.

The current timestamp is excluded from SDK evidence and native PRIOR history.
Original AND projected admission must permit; only a source-authored own mention
in an assigned unit can confer mention eligibility. No fake mention, force flag,
Slack post, host patch, transcript surgery or provider rewrite is used.

Normal, legacy busy, shared native burst, runner FIFO/merge/replay and nonrecipient
silence are exercised through pinned native methods with controlled SDK/model I/O.
This qualifies the supported input boundary, not a production SessionAuthority
storage deployment. Commands, DMs, bot/self and exact monitoring bypass semantics;
pending controls are rechecked after awaited work, including external failures.

Engineering bounds:6000 current characters,6000 history characters,6 messages,
6 units,4 recipients,96 questions,262144 serialized request/stdout bytes and16384
stderr bytes. Whole-ingress target2.5s with Jev at most1.2s, including remaining
budget at claim/publication. Blocking SQLite uses short transactions/timeouts;
cancellation kills/reaps native inference. OS/filesystem scheduling and cleanup
are not a hard real-time SLA. A failed/unavailable store logs and drops known
ordinary inputs; durability cannot be promised when storage itself is unavailable.
A disabled/broken plugin and unknown native mappings are not fail-closed guarantees.

## Verification

CI runs offline deterministic semantic/core tests in the `core` job on Python3.14.
The separate mandatory `native` job also uses Python3.14 for pinned native
integration, discovery/Doctor and a freshly built installed wheel outside source.
Real Jev calls are explicit local-only, use wholly fictional fixtures and require
no CI credentials. Set `JEV_FICTIONAL_CANARY_DIR` to a private new output directory
and select `test_real_fictional_native_product_client` in `tests/test_semantic.py`.
The full real journey test separately asserts five READY positive cases and one
unresolved case. Never replace failures with fixture answers or lower thresholds.
See [native acceptance](docs/native-acceptance.md) and [design](docs/design.md).

MIT license, copyright u1-liquid.
