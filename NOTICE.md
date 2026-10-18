# Provenance

The design was informed by octmicy/Mai_life at
3835b8f21efbcdb5bb3f6a4d89c568a51e60c6f7 (MIT), especially its separation of
rule-based state, schedules and planner-finalized opportunities. This project
does not copy its plugin implementation, database or runtime configuration.

It integrates with the independently maintained Neko plugins. Bridge signatures
use a versioned canonical packet compatible with neko-web's implementation.
No account cookie, provider key, private chat log or capability key belongs in
this repository or its release archives.

The host requires an HTTP(S) repository field even for unpublished local
plugins. That field currently points to the maintainer profile for manifest
compatibility, not a public Neko Life repository. Sources remain local until
the user authorizes publishing.
