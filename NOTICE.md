# Provenance

Neko Life is an independent repository, not a GitHub fork. Repository ownership
does not imply that every underlying idea originated here.

Its design and rule-based scheduling/state approach were informed by and adapted
from [octmicy/Mai_life](https://github.com/octmicy/Mai_life) at
`3835b8f21efbcdb5bb3f6a4d89c568a51e60c6f7`, licensed MIT, copyright
2026 时栖. The upstream copyright notice is retained in LICENSE. This is a
separate implementation with different scope, state schema and integration
boundaries; no upstream runtime database or configuration is distributed.

Neko Web, Neko Draw, Neko TTS and neko-proactive-mai remain separate projects
with their own licenses. Cross-plugin integration uses versioned APIs; the
release does not bundle their sources. Optional integration tests check out
fixed public revisions without copying private plugin runtime data.

No provider key, capability key, cookie, private chat, live SQLite database or
operator screenshot belongs in this repository or its release archives.
