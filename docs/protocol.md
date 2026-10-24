# Integration contract v1

The implementation baseline is MaiBot 1.3.9 / SDK 2.12. The host resolves API
visibility using the real caller ID but **does not pass that identity to the
receiving API handler** (`capabilities/components.py::_cap_api_call`). A caller
ID inside API arguments is therefore not trusted. No new host changes are required
for the cross-plugin bridge. Life0.5 sharing uses the already provisioned
`maisaka.reply.after_send` Hook alongside the native reply-extension protocol;
unpatched upstream hosts must not bypass component registration checks.

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

## Sharing candidate protocol2 (Life0.5 / Proactive2.2)

The signed `sharing_v1` API retains its envelope. `claim` returns protocol2,
receipt_id, kind, bounded summary/opinion/sources and fictional provenance.
`status` accepts only session_id and receipt_id and returns persisted state;
it never sends or retries. Host rejection before execution may release a lease.
An explicit `neko_life_skip_share` may decline only a still-unselected receipt.

The `neko.life.share` reply extension takes receipt_id but derives authorization,
persona, actual session/reply/call identifiers and source material from trusted
Host context plus the signed lease. It injects bounded generation requirements,
does not transform messages, and records expected segment count before send.
The correlated Host Hook confirms only complete, indexed, successful delivery
results with real message IDs. Neither a model-provided ID nor a normal QQ reply
anchor is delivery proof. Partial/error/missing results remain unknown; late
exact acknowledgements can settle idempotently. Adoption is not a semantic
guarantee that a model followed the material, nor proof of client display.

Unknown blocks that candidate, counts conservatively toward daily and backlog
limits, and is never replayed. New material can use remaining slots after the
independent Life cooldown. Sharing defaults are2/day,180minutes and8 unresolved
per session; original proactive scheduling/authorization is unchanged.

## Optional scene drawing details

`neko.draw.life_v1@1` is public but capability-authenticated, default disabled.
Its dedicated HMAC key is separate from Web and Sharing. The same packet schema
uses audience `neko.draw`, client `neko.life`, operation `submit`, and body
`{session_id,request_id,prompt}`. Issued time expires in120s; nonces persist for
600s (longer than both sides of the validity window). Requests persist before
generation with session/prompt digest; reuse with a different body fails.
An identical accepted request never generates again, even after a runner reload.
Ledger corruption, unknown schemas and full safety capacity fail closed.

Both plugins must enable the feature and allow the host-injected session.
Life's parameterless tool builds only a bounded current environment-scene prompt,
not an arbitrary prompt or portrait request. Its persona-local durable scene
dedupe and cooldown are consumed before calling Draw. The draw endpoint starts
the existing asynchronous generation/send engine; no image bytes cross the API
and no paid operation is awaited inside it. `submitted` is only admission, not
client delivery. Lost/unknown/reloaded work is never resubmitted automatically.
