# Native acceptance preparation

Status: authored, not executed. These are candidate tests, not evidence of a
working plugin. The production `plugin.Gate` and source-pinned bridge are still
absent. Native execution remains reserved until the originating requester resolves
the active local command guard. Do not run these commands to bypass that guard.

## Declared CI

`.github/workflows/tests.yml` declares Python 3.11–3.14 core tests, lint and package
build. A separate, unconditional Python 3.14 native job checks out official Hermes
revision `bf0203a794a07aac3ff764972ab9087baa4e4f4e`, installs that host's declared
`slack` extra in the runner environment and runs `tests/test_native.py` with
`HERMES_REQUIRE_NATIVE=1`. Missing source, dependencies or Gate implementation
must fail; no continue-on-error or native skip is accepted for that job. The full
host dependency install favors authoritative metadata over an unverified minimal
import list. Neither CI job has been executed for this candidate yet.

The local core command patterns select `test_core.py`, `test_boundaries.py` and
`test_storage_corruption.py` explicitly. Do not count the native module's optional
local skip as host validation. The native job must remain required for release,
even if repository branch protection has not yet been configured.

## Prepared fixture boundary

`tests/test_native.py` imports actual AsyncApp, SlackAdapter and GatewayRunner from
the isolated pinned checkout, not a copied host. A bare real GatewayRunner is
populated with native config/adapter/session fields, avoiding constructor startup,
live credentials and workers. Actual build_source, canonical identity resolution,
key generation, pending registries and core message listener remain intact.
External SDK responses and the final model handler are test boundaries. A public
second global middleware records whether the gate called next; it does not replace
host policy. Native cancellation cleanup is registered for spawned adapter work.
No test, fixture, host import or cleanup has run yet, so setup correctness remains
unverified. Fixtures may need native-state additions following the first real RED.

Prepared assertions cover silent secondary rejection, forged assignment text,
quote/code exclusions, legacy busy/merge exclusion, secondary-then-ordinary
ownership preservation, clarify choice/slash-confirm/update pass-through, unload,
and original video-file rejection before the native fallback. Flat body inputs
must remain unchanged. Rejection asserts empty 200 and no downstream listener,
model invocation, outbound chat/ephemeral, pending-message or text-batch entry.
This proves only the tested boundary once executed, not a real Slack session.

## Explicit remaining acceptance setup

The following must be added/exercised before claiming the design matrix complete:

- Positive main/secondary/multi-recipient model delivery after native burst flush;
  current secondary-positive case only checks unchanged assignment. Use native
  `_flush_text_batch_now(key)` and await owned tasks, not timing sleeps.
- Real shared-authority durable FIFO/busy burst, mixed text/photo ordering and
  denied native auth. A mocked final model handler alone does not prove those.
- Routed/multiplexed profiles with actual temporary registered profile directories
  and GatewayConfig profile_routes; match served-profile requirements. Never mock
  `_profile_name_for_source`, canonicalization, key readers or pending policy.
- Blocking dangerous-command approval through the real blocking approval queue;
  `submit_pending` writes a different registry and is NOT suitable evidence.
- Pending recheck after awaited metadata/storage, exact key mismatch, ambiguous
  workspace/receiver, workspace collisions and changed adapter on reconnect.
- Rich mention/code/quote/unfurl/forwarded composition, bot/self/API-human override,
  DMs/MPIMs, recognized slash/! commands (including behind mentions), exact
  monitoring exemptions, and unknown sender evidence diagnostics.
- Exact-channel file metadata absence, duplicate/ambiguous share, sender conflict,
  non-video, timeout, and both normal-message/file-notification arrival orders.
  Do not invoke the native fallback's built-in delay as a test synchronization
  technique; classify originals and observe transport/native execution boundaries.
- Socket Mode request-to-send_socket_mode_response receipt using the actual SDK
  handler and mocked socket I/O; AsyncBoltRequest socket_mode is not that receipt.
- Factory registration through actual PluginContext/manager, registration failure,
  late load, unload in-flight, restart-required replacement and isolated Doctor.

Keep these open in the implementation plan. Tests-first authoring is not RED
execution, independent review, integration acceptance or a release authorization.
