# Hermes Slack Thread Assignee

Stable main-recipient policy for multi-agent Slack channel threads.

## Development status

The local policy, shared SQLite store, terminal administrator and initial native
Gate/bridge are implemented. Actual pinned-host AsyncApp/native-method tests cover
the first integration boundary. Plugin discovery/manifest and host CLI activation
are not finished: installing this candidate does not automatically activate routing.
See [native acceptance](docs/native-acceptance.md), [design](docs/design.md) and
[implementation plan](docs/implementation-plan.md) for the remaining acceptance
criteria and the source-pinned integration boundary.

## Local core installation

Requires Python 3.11 or later. From a source checkout, use an isolated environment:

```sh
uv venv .venv
uv pip install --python .venv/bin/python .
.venv/bin/hermes-thread-assignee --help
```

This installs only the local command. Do not install it into a live Hermes profile
as if it were an activated plugin. Remove the package with the environment's
package manager when no longer needed; removing it does not delete the database.
No Slack credentials, remote classifier or external service are used by the core.

## Trusted local bootstrap and transfer

Copy `examples/config.json` and replace the fictional identities and absolute
storage path. All participating processes must use the same database path,
database identity, complete participant registry and registry revision. The
operator must create the database's immediate parent directory owned by the local
account with mode 0700. The explicit `init` command creates the database with mode
0600. Existing missing, corrupt, mismatched or unsupported databases are never
silently replaced. Only local filesystems on one host are supported.

```sh
hermes-thread-assignee --config /path/to/config.json init --dry-run
hermes-thread-assignee --config /path/to/config.json init
hermes-thread-assignee --config /path/to/config.json check
hermes-thread-assignee --config /path/to/config.json establish --workspace TDEMO --channel CDEMO --thread 100.001 --recipient alpha --if-absent --dry-run
hermes-thread-assignee --config /path/to/config.json establish --workspace TDEMO --channel CDEMO --thread 100.001 --recipient alpha --if-absent
hermes-thread-assignee --config /path/to/config.json show --workspace TDEMO --channel CDEMO --thread 100.001
hermes-thread-assignee --config /path/to/config.json transfer --workspace TDEMO --channel CDEMO --thread 100.001 --recipient beta --expected-revision 1 --reason 'operator handoff' --dry-run
hermes-thread-assignee --config /path/to/config.json transfer --workspace TDEMO --channel CDEMO --thread 100.001 --recipient beta --expected-revision 1 --reason 'operator handoff'
hermes-thread-assignee --config /path/to/config.json clear --workspace TDEMO --channel CDEMO --thread 100.001 --expected-revision 2 --reason 'operator reset'
```

`HERMES_THREAD_ASSIGNEE_CONFIG` may replace `--config`. Output and errors are JSON;
errors exit nonzero. Recipient arguments resolve to exactly one runtime profile
within the selected workspace. Mutations report the exact key, old/new recipient
and next revision. Dry-run checks the same CAS without committing. Clear retains
a revision tombstone: an old `--if-absent` cannot overwrite cleared history. Use
transfer with the observed revision to restore a cleared assignment.

The OS account is trusted. This is not isolation from another program running
under that account. No model tool or inbound message can mutate assignments.
Administrative mutation and audit insertion are one transaction. A policy decision
captures the main and direct recipient evidence atomically; a later transfer does
not rewrite that decision. Decisions currently remain indefinitely; pruning and
explicit schema migrations are not provided. Back up the database using SQLite's
consistent backup tools while no unsupported migration is attempted; never delete
it to hide a corruption or identity mismatch. Diagnose and restore a verified
consistent backup under local operator control.

## Core behavior and boundaries

Ordinary verified human messages select the durable main. Explicit known bot
mentions select only the addressed recipients, including multiple recipients;
secondary mentions never transfer ownership. Human/nonparticipant mentions do not
displace main. Flat quoted/code text is excluded. Rich Slack composition and
verified sender/receiver/native pending-state extraction belong to the upcoming
host bridge; do not feed rendered messages or quoted block contents to the flat
parser. Unknown/ambiguous receiver or mismatching event evidence returns native
pass-through with a reason, not a guessed recipient. Unknown main or unavailable
storage drops known ordinary inputs. Native permission checks remain authoritative.

## Development checks

```sh
python -W error::ResourceWarning -m unittest discover -s tests -v
uv tool run ruff check .
uv tool run ruff format --check .
uv build
```

The native test module additionally exercises actual pinned-host methods with
synthetic SDK responses. Socket transport receipts, shared-authority/routed paths,
Plugin Doctor and release lifecycle coverage remain incomplete. See
`docs/native-acceptance.md` for the precise boundary; CI still must execute on the
published candidate before release.

MIT license, copyright u1-liquid.
