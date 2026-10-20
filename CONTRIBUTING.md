# Contributing

Keep the plugin small and composable. Use typed, bounded domain services and
thin SDK adapters rather than importing the host's private Python modules.

```bash
python -m pip install -e ".[test]"
python scripts/test_suite.py
python -m ruff check .
python -m ruff format --check .
python scripts/build_release.py
```

Tests must use synthetic data and fake providers/QQ/model calls. Do not add a
live access key, browser state or production data fixture. Optional ecosystem
tests need adjacent neko-web, neko-proactive-mai, neko-draw and neko-tts source
directories; CI declares the pinned versions. A skip is not integration proof.
The guarded runner rejects missing discovery (<75 tests) and all skips. The CI
matrix runs Python 3.12/3.14 on Linux/Windows with SDK 2.12.0 and latest 2.x.
For local pinned archives, set NEKO_LIFE_ECOSYSTEM_ROOT to their parent directory;
do not validate against unreviewed adjacent development branches.

Preserve fail-closed credential/database behavior, replay protection, existing
chat policy and the distinction between simulated scenes and sourced facts.
No automatic restore/replay of uncertain external work. A successful host task
submission is not a delivery receipt. Do not remove safeguards or fabricate
evidence to make a test green.

Use one Conventional Commit per shippable change, document API compatibility
and migration requirements, and keep release files on the explicit allowlist.
