# Security and privacy

Never include a provider API key, capability key, access token, login QR URL,
private chat, live database, cookie export or unredacted screenshot in an issue.
Report minimal examples with synthetic data; use GitHub private vulnerability
reporting if available for a sensitive report.

The supported host knows API callers but does not pass a trustworthy caller ID
into the receiving handler. Cross-plugin operations use per-client HMAC keys
and persistent nonces. Signatures bind audience, operation, body and timestamp.
Keys live in private data files (0600 on POSIX). This is not an OS sandbox:
other processes under the same service account can read its files. Windows
mode bits do not replace NTFS ACLs.

Provider credentials stay in neko-web. External research receives the public
query and URL, not these capability keys. Chat topics are not mined by default,
but operator-supplied persona/interests can contain sensitive information; do
not put identities, private URLs or secrets there. Rejection patterns are a
secondary layer, not guaranteed anonymization.

Web pages and snippets are untrusted data. Research cannot run shell commands,
log in, post, purchase, download executables or invoke arbitrary tools. Model
summaries may still be mistaken or influenced by hostile content; review their
sources. A simulation diary or scene is never real-world evidence.

Zero daily cost limits disable those budgets only. Concurrency, timeouts,
bounded input/output, queues, source guards, deduplication and chat anti-spam
remain. Exact costs cannot be guaranteed for hidden reasoning, continuation
or missing usage reports.

Unknown requests or messaging acknowledgements are not automatically replayed.
Submitted is not delivered. Ordinary QQ anchors are not exact task receipts
without evidence. Autonomous scene illustrations require independent switches
and session allowlists in Life and Draw, plus a dedicated per-client key. The
Draw endpoint verifies the signed operation, target, prompt and request ID,
persists admission before generation, and never replays unknown work. This
authorization is separate from ordinary drawing tools. Life exposes no arbitrary
prompt parameter: only current fictional environment scenes, without portraits.
Self portraits stay on the existing memory-first explicit drawing path.

Configuration and SQLite notes are unencrypted at rest. Back up private data
separately. Corrupt/unknown schemas fail closed with the original file retained;
never upload such a file publicly as a debugging attachment.
