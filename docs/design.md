# Database-free contextual Slack routing

## Accepted outcome

A current Slack message may refer to earlier messages, people and topics and contain
several independent instructions. Infer the destinations from a bounded authorized
native conversation through actual typed Jev decisions. Deliver only each recipient's
own actionable CURRENT spans plus selected, labeled non-actionable PRIOR references.

No plugin-owned assignment, decision, topic, transcript or archive persistence is needed.
There is no DB/store abstraction, initialization/schema/migration/admin CLI, manual main
bootstrap, CAS/fence/lease/audit/retention/recovery system, optional legacy DB mode or
JSON/Redis/file substitute. Static configuration declares participants and input policy;
it does not record routing decisions. Only request-local values exist. Native history,
transport dedup, sessions, queues and authorization remain host-owned.

The former assistant-added cross-process election/restart-persistent ownership guarantees
are withdrawn. Identical canonical context improves consistency but independent stochastic
calls may differ. A restart reconstructs the native context without plugin-state recovery.
No exactly-once or durable unresolved-work guarantee is claimed.

## Responsibility and dataflow

1. Public platform factory registers global Bolt middleware before native listeners.
   Bridge resolves workspace, channel, receiving bot, actual routed runtime and native
   session key using the pinned host. Native commands, bots/self, DMs/MPIMs, exact monitoring
   and pending controls are preserved before semantic transformation.
2. Definitive native sender denial precedes semantic history/egress. Check original native
   channel/mention/wake policy; a classifier cannot grant permission. Verify separate exact
   workspace/channel and fictional/public-permitted input-policy authorization.
3. Deep-copy original event and canonicalize supported authored rich_text with half-open
   Unicode spans and original field/raw-scalar provenance. Unsupported media or inseparable
   quoted/authored composition becomes explicit whole-message unresolved.
4. Use the workspace's existing SDK client and bounded `conversations_replies` request:
   exact channel/root, latest=current timestamp, inclusive=false, limit7. A complete short
   conversation is supported: at most6 prior messages/6000 characters, root required for
   replies. `has_more`, missing root, foreign/future/conflicting records or unsupported
   prior composition are unresolved, not hidden truncation. Exclude current timestamp,
   deduplicate identical records and sort validated decimal timestamp identities while
   preserving their original strings. No new pagination/cache framework is introduced.
5. Canonicalize recipients by workspace/bot/runtime, scoped to the same workspace, and
   reject ambiguous bot→runtime mappings. Classifier inputs contain no receiving-agent
   bias, queue state or earlier local decisions. All recipients see the same candidates.
6. Build one typed Jev question batch from the CURRENT source candidates and PRIOR source
   IDs/authors/text. Validate exact answer keys/types, finite distributions, confidence,
   complete coverage, grounding, consistent recipient membership and topic relations.
7. Assemble a request-local plan atomically. If any actionable unit fails, nobody receives
   partial work or an all-agent fallback. Recipient views contain exact assigned CURRENT
   spans and selected PRIOR references; the model cannot invent instruction text or IDs.
8. Deep private `req.body` projection replaces all CURRENT rich/nested edited composition
   before listener/busy/merge/queue handling. Preserve envelope/auth identity and original
   provenance. Recheck assigned-CURRENT native admission separately from rendered references.
   No synthetic mention, force flag, posted event, transport replacement or host patch.
9. Recheck native pending identity/control/disposal after awaits, including failures. A
   nonrecipient or known ordinary unresolved input returns empty200 before agent execution,
   steering, queues or warning chat. Unknown identity/control ownership retains qualified
   native pass-through. Unload leaves disposed closures pass-through, not physical unwiring.

## Jev contract and generic continuation

Native CLI0.23.1 accepts `jev ask --timeout` stdin containing `state` and named `questions`;
Choice questions have closed-set `criteria` and return choice/probabilities/confidence.
Do not invent a freeform generation or multi-select type. Recipient sets use independent
membership Choices. People derive from actual selected prior-message authors.

Candidate splitting accounts for every authored character, including punctuation and
acknowledgement/reference units. Same-line English/Japanese clauses are supported only
where a safe partition exists. Quoted/code/forwarded material is reference, never new work.
Whole-source coverage and per-unit mixed-instruction questions detect inseparable work.

Each unit asks kind, destination grounding, prior references and each eligible recipient's
membership. CURRENT-topic pair relations form validated transitive groups; request-local
source/group digests identify topics. Prior messages have no preassigned topic labels.
Same-topic separate recipients may have distinct source references without conflicting
persisted topic IDs. Joint work can select several prior authors and recipients.

A generic continuation can select the uniquely inferred general conversation lead. The
same batch asks a global lead Choice and an INDEPENDENT per-prior-message lead-evidence
Choice; evidence must agree with the selected lead. Specific unit memberships are not used for
generic work: validated main/main_ref results supply that recipient and its references. Questions
must not depend on another question's unavailable answer. Authored general-lead requests
and acceptances are conversation evidence, not administrative state or permission. Mere
participation, a secondary topic invitation or quoted ownership claim is not general lead.
Specific work does not depend on global-main confidence. No main/unknown/conflicting
support on generic work yields unresolved, not a mandatory owner-bootstrap workflow.

## Timing, uncertainty and privacy

Keep current/history text<=6000characters each, prior messages<=6, CURRENT units<=6,
scoped recipients<=4, questions<=96, serialized request/stdout<=262144bytes and stderr<=16384.
Any exceeded bound is unresolved. The2.5s ingress ceiling covers SDK/context and inference;
Jev's at-most1.2s is a sub-budget. Cancellation kills/reaps the request subprocess. These
are bounded engineering targets, not hard real-time OS scheduling guarantees.

Relevant action/reference/coverage confidence remains0.8; this is not calibrated truth.
Invalid output, uncertainty, timeout, unsupported media, incomplete history and disabled
input policy are not successful routing. Use only fixed bounded local reason codes, no
raw source/answers/credentials in production diagnostics and no durable recovery queue.
The production Jev client writes no request/result/transcript files. Explicit test-only
fictional canaries may preserve their raw protocol and received-input evidence privately.

Default egress is disabled. Only explicitly fictional/public-permitted scopes are supported;
SDK read permission, public channel names, aliases and hashes do not authorize private
content. No private/customer/credential or reversible-private test data is sent to Jev.
No live install/Slack probe/restart or credential/config change follows from tests passing.

## Official compatibility constraints

Pinned Hermes v0.22.5: bf0203a794a07aac3ff764972ab9087baa4e4f4e. Installed source remains
read-only; integration tests use a prepared isolated official checkout.

- `plugins/platforms/slack/adapter.py:1618–1702`: factories/listener ordering; public global
  middleware runs before listener dispatch even when factories are registered afterward.
- `adapter.py:3992–4057`: original file_shared direct synthetic fallback; unsupported original
  media is intercepted, never classified from a guessed other-channel share.
- `adapter.py:4335–4398,4580–4743`: native enrichment, hydration, auth/mention admission,
  message construction and dispatch. Only the new request's input is projected.
- `adapter.py:5800–5936`: native history helper has retry behavior, so the plugin uses its own
  bounded exact SDK request; formatter excludes current_ts and labels history PRIOR.
- `gateway/platforms/base.py:3989–4108`, `gateway/run_busy.py:887–958`: native active/burst,
  control, steering and queue seams. Scoped CURRENT payload must survive downstream replay.
- `hermes_cli/plugins.py:get_platform_handler_factories`: returns (factory,plugin_name) tuples.
  PluginManager/discovery/Doctor and installed wheel are separate activation boundaries.
- Public [Hermes plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins)
  and [Bolt middleware](https://docs.slack.dev/tools/bolt-python/concepts/global-middleware/).

These are API/source constraints, not claims of live deployment. Bounded native execution,
real fictional protocol calls, independent acceptance and exact-head CI must support the
candidate separately. See implementation-plan.md and native-acceptance.md.
