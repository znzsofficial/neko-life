import importlib.util
from pathlib import Path
import tempfile
import unittest

from neko_life.store import Store

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("life_budget_review", ROOT / "scripts/review_budget.py")
review_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review_module)


class BudgetReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_overshoot_within_daily_envelope_preserves_counters_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            await store.call("open")
            await store.call("reserve", "p", "model", "one", 5000, 1000)
            await store.call("settle", "p", "one", {"prompt_tokens": 1055, "completion_tokens": 2458})
            await store.close()
            preview = review_module.review(directory)
            self.assertTrue(preview["reviewable"])
            result = review_module.review(directory, approve=True)
            self.assertTrue((Path(directory) / result["backup"]).exists())
            store = Store(directory)
            await store.call("open")
            try:
                self.assertEqual((await store.call("usage", "p"))[0]["calls"], 1)
                self.assertEqual(await store.call("output_allowance"), 5542)
            finally:
                await store.close()

    async def test_unknown_usage_cannot_be_forgiven(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            await store.call("open")
            await store.call("reserve", "p", "model", "unknown", 5000, 8000)
            await store.close()
            with self.assertRaisesRegex(ValueError, "unknown_usage"):
                review_module.review(directory, approve=True)
            self.assertEqual(len(list(Path(directory).glob("life-budget-review-*.db"))), 0)
