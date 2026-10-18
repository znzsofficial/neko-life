# Validation boundaries (2026-10-18)

The complete OpenChamber plan is not yet finished. This is an enabled 0.2
delivery with explicit evidence boundaries, not an assertion that every route
has been exercised in production.

- Installed host: MaiBot 1.3.9 / SDK 2.12.0. Real PluginManifest,
  WebUIExtension and Context Items deserialize/serialize checks pass.
- Isolated three-plugin research/receipt tests use synthetic web results,
  fake model responses, actual SDK API-envelope normalization and fake send
  acknowledgements. They do not call providers or QQ.
- Real Life activation and private authenticated workspace status query pass;
  the main MaiBot process remained unchanged. Plugin Runner reloads did occur.
- Real first schedule model call reported 1055 input / 2458 output despite a
  requested 1000-token output. The first ledger froze safely. After explicit
  reviewed reconciliation with a full database backup, usage stayed charged
  against the original daily 8000 envelope. No budget limits were raised.
- A real capability signature reached Web, and a model-selected exploration
  round chose to skip. No source note exists from that round. Do not forcibly
  reset its interval/counters or send QQ merely to manufacture success evidence.
- Original proactive target/probability/window/intent settings and all other
  plugin configuration sections were hash/semantic checked. Only new bridge
  sections and new Life configuration were introduced.
- The operator approved enabling exploration and existing-target sharing and
  accepted loss of in-memory cooldown on source reload. This did not authorize
  autonomous drawings or a new public repository.
- Browser visual verification is blocked by the host login screen; schema and
  live query validation are not desktop/mobile screenshot approval. Mechanical
  declarative-source design check reports no findings.

Remaining natural-use checks: ongoing autonomous topic quality, exact QQ/TTS
delivery attribution and independently authorized autonomous drawing. Success
on an explicit administrator research request does not prove an autonomous
selection or message delivery. Unknown receipts must stay unknown.

## Subsequent authorized progress

The operator explicitly requested disabling cost limits and continuing remaining
work. All six Life daily cost limits and both Web daily limits were set to zero
(unlimited), while concurrency, request bounds, failures/unknown-work guards,
dedupe and chat cooldown remain. Ledger history was not cleared. The new release
supports configurable intervals without silently changing the live two-hour
automatic cadence.

An explicit administrator exploration successfully searched Exa, read two NASA
official pages through the protected public downloader, and saved one note with
body-vs-snippet provenance. This proves the live retrieval-to-note path, not an
autonomously chosen topic or a QQ delivery. Further sources remained snippets.
Desktop (1440px) and mobile (390px) management pages were checked at both top
and bottom using a temporary SSH forward and private in-memory login. No token,
cookie state or login screenshot was exported. Both viewports have document
width equal to viewport width. English statuses/raw quota JSON were replaced
with readable labels; long notes were changed from cramped table columns to
full-width paragraphs. The host's existing mobile navigation/live-activity
overlay can transiently cover the bottom edge; this plugin does not replace it.
Screenshots stay in the approved local temporary directory, not source/Git.

Regression: Web108 / Life44 / proactive24 pass with actual SDK 2.12, including
disabled-cost accounting, preserved queues/intervals, terminal result eviction
without duplicate execution, midnight/DST/offline idempotency, and real Host
image plus tool-call/output serialization roundtrip. Rapid completed SQLite
work exposed a false pending-queue count; fixed by exactly-once release on
completion, not by increasing the queue limit or removing the test.

Rollback order: disable Life and the proactive Life bridge, retain all new
databases/outbox/keys, then restore matched service versions and their earlier
configuration using verified backup/update procedures. Unknown jobs must not be
replayed after rollback. A restore has not been deliberately induced against
the active chat service as a test.
