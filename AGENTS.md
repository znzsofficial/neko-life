# Neko Life

- Implement the approved OpenChamber plan; tick only completed, tested steps.
- Independent project. User authorized public open-source release after completion
  and verification on 2026-10-18; never publish runtime configuration or data.
- Default disabled. Real model/search/QQ sends and autonomous drawings have
  separate rollout gates. Never treat task submission as delivery success.
- No host/persona/history mutation. No direct autonomous send. Public web facts,
  personal opinions and simulated scenes must remain distinguishable.
- Search provider keys live in neko-web, not here. Bridge authentication uses
  private per-client capability keys, not self-reported caller identity.
- Keep SQLite IO on a serialized worker, bounded queues, durable reservations,
  no automatic replay of uncertain external work, and fail closed on corrupt DBs.
- All tests use synthetic data and fake time/providers. No new paid validation.
- Preserve existing proactive policy, TTS instruction/15%, draw memory-first
  self portraits, and media limits. No browser automation or private chat mining.
- Run unittest and Ruff. Document unknowns instead of claiming live acceptance.
