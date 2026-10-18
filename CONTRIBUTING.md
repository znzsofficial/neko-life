# Contributing

Keep the plugin small and composable. Use typed, bounded domain services and
thin SDK adapters rather than importing the host's private Python modules.

```bash
python -m pip install -e ".[test]"
python -m unittest discover -s tests -t . -q
python -m ruff check .
python -m ruff format --check .
python scripts/build_release.py
```

Tests must use synthetic data and fake providers/QQ/model calls. Do not add a
live access key, browser state or production data fixture. Optional ecosystem
tests need adjacent neko-web, attention-seeker-mai, neko-draw and neko-tts source
directories; CI declares the pinned versions. A skip is not integration proof.

Preserve fail-closed credential/database behavior, replay protection, existing
chat policy and the distinction between simulated scenes and sourced facts.
No automatic restore/replay of uncertain external work. A successful host task
submission is not a delivery receipt. Do not remove safeguards or fabricate
evidence to make a test green.

Use one Conventional Commit per shippable change, document API compatibility
and migration requirements, and keep release files on the explicit allowlist.
