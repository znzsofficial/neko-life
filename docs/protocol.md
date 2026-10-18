# Integration contract v1

The implementation baseline is MaiBot 1.3.9 / SDK 2.12. The host resolves API
visibility using the real caller ID but **does not pass that identity to the
receiving API handler** (`capabilities/components.py::_cap_api_call`). A caller
ID inside API arguments is therefore not trusted. No host changes are required.

Cross-plugin operations use a single bounded JSON packet, authenticated by a
separate per-client HMAC-SHA256 capability key. The signed bytes bind protocol
version, audience, client, issue time, nonce, operation and body. Requests expire
after 120 seconds; persistent nonce uniqueness prevents replay. Each receiver
has its own keys. Never reuse the web and sharing keys. Keys are local files,
0600 on POSIX, outside plugin sources. This is capability authentication, not
OS isolation: code running as the same service account can read those files.

All new endpoints are off by default. No keys are generated or copied by plugin
startup. An administrator must provision and review the bridge before enabling
it. No endpoint trusts a caller-supplied user ID for private data access.

`neko.web.automation_v1@1` accepts submit/get/cancel/capabilities operations.
Submit returns immediately. Search and read run outside RPC lifetime. Signed
get/cancel must use the same authenticated client. Idempotency is scoped to
client + request_id; reuse with a different body is rejected. Jobs survive
reload as terminal results or `unknown`, never automatically resubmitted.

Search uses the configured provider. Unsupported structured provider formats
fail explicitly, not by parsing display text. A read is bounded public text,
never images, browser execution or delivery. The existing public fetch checks
and provider credentials remain owned by neko-web. Manual tools remain usable
with the bridge off and do not consume its background quotas.

Host RPC budgets must be tested against the installed SDK; long operations are
never awaited inside public APIs. Life prompt hooks use local snapshots only.
Sending a host proactive request is not proof of QQ delivery. Without reliable
task attribution, sharing remains `unknown`, with no automatic retransmission.

Preservation baseline: no changes to persona, ordinary chat history, TTS voice
instruction/15% selection, draw memory-first self portraits, inactive plugins,
CPA credentials, proxy selection, or existing proactive targeting/probability.
