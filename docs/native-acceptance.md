# Stateless native acceptance boundary

## Host and candidate

Pinned official Hermes v0.22.5, bf0203a794a07aac3ff764972ab9087baa4e4f4e;
Python3.14, Slack Bolt1.30.0 and Slack SDK3.44.1 via tests/requirements-native.txt.
The candidate uses request-local context/typed-Jev plans and private Bolt projection.
There is no plugin assignment/decision/topic/transcript store, admin/init CLI or manual
main bootstrap. Discovery and startup require only static participants/input policy.
CI retains distinct required core/native jobs on Python3.14, not an interpreter matrix.

## Executed versus controlled boundaries

`tests/test_native.py` uses actual AsyncApp dispatch, SlackAdapter listeners and native
GatewayRunner identity/session/pending/queue methods. Only external SDK I/O and the final
model/busy receivers are controlled. Offline native tests control Jev answers too; they
are not claimed as external model inference. Assertions inspect the receiver's actual
CURRENT text, not just a classifier label.

- Both recipients get disjoint assigned CURRENT spans and relevant labeled PRIOR sources.
  Nonrecipients get empty200 before native model/chat/warning/queue/steering.
- Rich/nested edited input is canonicalized with exact Unicode/source-field provenance;
  private projection removes excluded blocks/files/attachments, preserving caller originals.
- Native original/projected authorization and mention/wake admission intersect. A mention
  in somebody else's action or rendered PRIOR text cannot manufacture wake permission.
- Normal handling, legacy busy, shared native burst, runner FIFO/promotion/merge/replay
  retain scope. This is not a separate deployed SessionAuthority persistence system.
- Commands, bots/self, DMs/MPIMs and exact monitoring keep native handling. Genuine blocking
  approval, clarification, slash confirmation and update controls bypass/recheck after awaits,
  including SDK/Jev failure. Short control replies do not become new broad work.
- Current timestamp is excluded. Root/current media and incomplete/foreign/future/conflicting
  history are unresolved. Opposite receivers with reversed registry/history produce the
  same canonical question batch. Edited input reclassifies rather than reuses stored state.
- Native duplicate accepted-event suppression survives while plugin classification may
  run again. A fresh Gate reconstructs prior references from native history without DB/init.
- Socket Mode sends exact empty acknowledgement, unknown native identity is not guessed,
  runtime/transport rebinding remains checked and disposed callbacks pass through.

`tests/test_semantic.py` exercises exact spans, selected source authors, current topic
groups, joint recipients, multilingual ACK/new-work, quoted context, generic lead/source
support without bootstrap, atomic uncertainty, typed distribution/key/confidence validation,
request/output caps and actual native subprocess cancellation/reaping. `test_boundaries.py`
checks canonical inputs, edits and workspace/ambiguous-identity isolation. DB lock/schema/
migration/CAS/audit/purge/election tests are intentionally removed with the rejected store.

## Explicit real fictional inference

`JEV_FICTIONAL_CANARY_DIR` opts into real Jev CLI0.23.1 through the production
prepare→JevClient.ask→assemble path. The semantic journey test requires READY/correct
scopes for two topics, contextual unmentioned reply, ACK/new work, same-topic multiple
recipients, quote/reference and a generic lead inferred from conversation; ambiguous
addressee requires unresolved/no views. The native real-Jev test additionally drives
actual AsyncApp→SlackAdapter input for both recipients of a multi-topic message, an
unmentioned contextual reply and a generic continuation. SDK history and final model
receiver remain controlled; inference is external and real, not replayed fixture answers.

Raw request/result/exit/latency, plan and native received-text artifacts belong only to
the opt-in test harness. Production has no filesystem transcript/decision capture. No
private Slack/customer/credential/reversible-private fixture or CI credential is used.
Confidence0.8 is preserved, not tuned to make canaries pass. These are bounded fictional
examples, not calibrated accuracy: uncertain answers remain no-work, not synthetic success.

## Packaging/startup and independent acceptance

`test_core.py` launches a fresh standard-library-only subprocess that parses DB-free
config and registers the plugin without init/owner setup or routing files. It does not
activate Slack SDK middleware in the SDK-free core lane. The separate required native
`test_plugin_surface.py` runs real directory discovery, actual factory activation and isolated
Plugin Doctor with no admin command. `test_installed.py` runs Python-I outside the source
checkout against a fresh separate wheel target, verifies the real entry point and factory,
and rejects stale Store/PlanStore/admin modules/console scripts. Source-suite wheel skips
are not wheel proof; native CI explicitly requires the separate installed-wheel gate.

The current source must pass complete local suites, Ruff/check-format/diff/build, fresh
wheel/native gates, one consolidated independent review and exact-head hosted core/native.
Implementation self-checks, prior persistent-product acceptance and scalar code-quality
scores do not supply current independent stateless acceptance. Historical private evidence
remains at its original source/behavior boundary, not relabeled as database-free proof.

## Limits and unperformed operations

Context is a bounded complete short thread (root plus at most6 prior messages/6000characters).
`has_more`, unsupported/inseparable composition, missing/ambiguous lead and failed Jev produce
bounded fixed local diagnostics and empty ordinary acknowledgement, not durable recovery.
Only request-local memory exists; repeated events/processes/restarts can classify again and
independent stochastic plans may differ. Native history/dedup are not plugin consensus.

Default semantic egress is off; exact fictional/public-permitted policy is required. Native
auth/control/wake remains authoritative. No atomic native control lease or universal
fail-closed coverage is claimed for disabled/broken plugins/unknown native mappings.
Ingress target2.5s and Jev<=1.2s include bounded I/O and cancellation cleanup, not a hard
OS scheduling SLA. Physical middleware unwiring is unsupported; replacement/re-enable
needs an operator-managed restart. No live install/Slack probe, private egress, real DB
file deletion, Gateway restart, merge/release or deployment is performed by these tests.
