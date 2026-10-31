# Stateless implementation plan and verification map

Outcome: native conversation→actual Jev message/person/topic decisions→recipient-specific
CURRENT instructions, with no plugin-owned assignment/decision/topic/transcript persistence
or manual owner administration. [design.md](design.md) defines the accepted database-free
architecture. This supersedes the unreleased persistent-design plan and its old tests.

## Coherent implementation batch

- Remove Store/PlanStore/admin CLI, schema/migration/CAS/fence/lease/audit/recovery/retention
  machinery, database/ID/registry-revision settings, console entry point and DB-only tests.
  Do not retain a dormant abstraction, legacy mode or substitute durable store.
- Reuse Bridge/native identity/pending and public Bolt middleware. Request-local Snapshot,
  Jev Choice decisions, Plan/Unit/view and private req.body projection are sufficient.
- Use the exact bounded native SDK context, canonical participant/source ordering, current
  timestamp exclusion, root/identity/media validation and default-disabled egress policy.
- Infer general conversation lead and supporting prior sources within the SAME Jev batch.
  Specific requests use per-unit recipient/reference decisions; generic continuations use
  validated main/main_ref decisions, not redundant per-unit specific-membership answers.
  Unknown/failed actionable scope is atomic unresolved, never all-agent fan-out or partial loss.
- Keep native sender/channel/mention/wake authorization, commands, DMs/bots/monitoring and
  pending approval/clarification/confirmation/update handling. Preserve busy/queue/replay
  scope and native transport dedup without a cross-process exactly-once promise.
- Replace all production Jev subprocess/executable/CLI-auth dependence with direct bounded
  asynchronous official System One HTTPS. Declare only httpx, enter the bound native runtime
  secret scope and resolve TYPESAFE_API_KEY per request. No credential/config migration,
  cached key, redirects, retries, logged response bodies or detached timeout work.
- Rewrite public config/package/README/design/native acceptance to the actual stateless
  product. Production Jev has no filesystem capture; opt-in fictional tests own raw evidence.

## Acceptance map

| Outcome | Executable boundary |
| --- | --- |
| Fresh startup without database/init/admin/bootstrap | test_core SDK-free fresh subprocess→config/register; mandatory native PluginManager→factory/middleware/Doctor; outside-checkout rebuilt wheel |
| Two topics/two recipients and exact actionable scope | deterministic semantic spans plus real AsyncApp/SlackAdapter received CURRENT and both-recipient controls; explicit real Jev native canary |
| Unmentioned contextual reply; mixed ACK/new work | source-reference and multilingual controls; explicit real Jev journeys |
| Same-topic joint recipients and separate prior authors | semantic group/reference controls; actual native scoped receiver/reconstructed Gate |
| Generic continuation without manual owner | same-batch lead/source evidence controls; ambiguous/conflicting lead→unresolved; explicit real semantic/native generic canary |
| Quoted/forwarded/code as context only | canonical source/provenance controls and quote canary; no quoted current action or wake token |
| Uncertainty/failure/partial coverage | atomic empty views, strict typed keys/distributions/relevant confidence, HTTPS status/redirect/transport/timeout/cancel/body caps, native empty ACK/no model/warning |
| Official API and Hermes credential scope | production client URL/Bearer/JSON/no-CLI tests; real native request-profile and concurrent multiplex isolation, missing/unscoped key no-egress; actual fictional API/native canaries |
| Shared canonical inputs and isolation | sorted registry/history equality across opposite actual receivers; cross-workspace/foreign/future/conflicting/incomplete evidence rejection; edited source reclassification |
| Native safety and operational paths | real sender denial before context/Jev; original/projected native gates; pending before/after awaits and failures; normal/legacy busy/shared burst/FIFO/merge/replay, bots/DMs/commands/monitoring/unload |
| Packaging and current CI | Ruff/check-format/diff/build; actual discovery/Doctor, installed wheel; exact-head core/native on Python3.14 with unchanged required rules |

## Delivery sequence

1. The no-store architecture/removal phase is accepted historical input; do not replay it.
2. ACK the selected API delta, execute transport/credential RED, then coherently replace
   production CLI with HTTPS and request-scoped Hermes credentials; preserve all semantics.
3. Run complete current local gates, actual fictional Jev and native received-input checks.
   Preserve failures and distinguish controlled external SDK/model receivers from real Jev.
4. Freeze the candidate and obtain one consolidated independent Ritsuko acceptance on the
   same task. Remediate necessary findings under one writer, then verify the affected bridge.
5. Ordinary update to existing feature PR1 only; read back exact branch/head/body and every
   current required core/native job before native task completion. No merge/release/deploy.

Historical private persistent-product evidence stays historical. No live install, private
context egress, Slack probe, real DB-file deletion, Gateway restart, core/profile/policy edit,
new repository/task graph or force/main push is part of this plan. Implementation self-checks
and external model canaries do not supply independent acceptance or deployment permission.
