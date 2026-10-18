# Release verification and boundaries

## Supported release contract

Neko Life 0.3 is the first public release of the implemented research, schedule,
context, management and optional sharing integration. "Release complete" does
not mean every future provider response or QQ client has been demonstrated.

Autonomous drawing is deliberately excluded by the approved safety gate: the
supported host does not give the drawing tool enough trusted origin evidence
to distinguish an explicit request from an unrequested life suggestion. Only
explicit-request scene context is supported; no autonomous-image switch or
background spend path is advertised.

Sharing has exact success and conservative unknown paths. A host submission is
not a delivery. Without an exact task/session success acknowledgement, it stays
unknown and is not automatically replayed. This is verified behavior, not an
unimplemented promise to infer delivery from ordinary chat content.

## Evidence

- Baseline host: MaiBot 1.3.9 / SDK 2.12. Real manifest, declarative workspace and
  image plus function-call/output Context Items serialization checks pass.
- Six-plugin isolated preflight passes: Web108 / Life56 / proactive24 / draw53 /
  TTS63 / video45 = 349 tests. Providers, model calls and send receipts use fake
  services and synthetic media; no paid test or QQ message is emitted.
- The public CI matrix requires Python 3.12 and 3.14 on Linux and Windows,
  SDK-backed integration tests with pinned adjacent plugin sources, Ruff checks
  and an allowlisted release build. Missing integration checkouts are explicit
  skips, not evidence of compatibility.
- An initial Windows run detected temporary directory cleanup before SQLite
  closure. The fixture now uses an async exit stack so databases close before
  the directory is removed; neither Windows nor the failed assertion is skipped.
- Real approved research searched Exa, read two NASA official pages and saved
  one source-bound note. Other results remained snippets. That round used an
  administrator's topic, not an autonomously selected topic or QQ delivery.
- Live signed bridge requests, original plugin settings and a private workspace
  query were checked. The main host process stayed unchanged; Runner reloads
  did occur. Unknown sharing state is retained rather than relabeled as sent.
- The operator disabled all six Life and two Web daily cost limits. Ledger
  history remains, and concurrency, size/time bounds, dedupe and chat policy are
  separate from cost budgets. Positive budgets remain available for new users.
- Desktop1440 and mobile390 workspace top/bottom views were inspected. Long notes
  use full-width text and the document fits each viewport. The host's own mobile
  activity bubble can transiently cover its bottom edge; host UI is not replaced.
  Temporary screenshots and private login state are not public release assets.

## Security and reproducibility

The working tree, all reachable Git objects and ZIP were checked against the
live deployment's key/token material without printing or storing that material.
Runtime configuration, capability keys, SQLite files, private chat and operator
screenshots are excluded. Source provenance, MIT notices, an explicit pairing
script, public install instructions and reporting guidance are included.

ZIP membership is allowlisted and metadata fixed; two builds in the same
environment produce identical bytes. Asset SHA256 must match the published
checksums and hosting-service digest before announcing the release.

## Operations

Back up source, configuration, capability keys and a consistent SQLite snapshot
before upgrading. Disable Life/its sharing client before rolling back matched
versions, retain unknown-job/outbox evidence and do not replay uncertain work.
Do not let an older plugin open an unknown database schema. A rollback is not
deliberately induced against active chat merely to manufacture test evidence.

Natural use remains important: provider drift, model-generated note accuracy,
QQ/TTS rendering and exact receipt availability cannot be guaranteed by mocks.
Treat contradictory user feedback or diagnostics as evidence to investigate,
not as a reason to erase history or turn an unknown result into success.
