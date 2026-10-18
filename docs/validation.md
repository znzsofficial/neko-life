# Validation boundaries (2026-10-18)

The complete OpenChamber plan is not yet finished. This is an enabled 0.1
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

Remaining natural-use checks: successful real search and bounded body reading,
source note quality, host hook composition with media/TTS, precise QQ task
attribution, desktop/mobile management rendering and independently authorized
autonomous drawing. These must not be relabeled as passed because an offline
test or config toggle succeeded.

Rollback order: disable Life and the proactive Life bridge, retain all new
databases/outbox/keys, then restore matched service versions and their earlier
configuration using verified backup/update procedures. Unknown jobs must not be
replayed after rollback. A restore has not been deliberately induced against
the active chat service as a test.
