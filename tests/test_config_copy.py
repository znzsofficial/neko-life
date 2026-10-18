import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("maibot_sdk"), "SDK required")
class ConfigurationCopyTests(unittest.TestCase):
    def test_every_operator_field_has_chinese_label_and_help_without_changing_defaults(self):
        from neko_life.config import Settings
        from maibot_sdk.config import generate_plugin_config_schema
        import json

        cfg = Settings()
        schema = json.dumps(generate_plugin_config_schema(Settings), ensure_ascii=False)
        self.assertIn("自己上网找见闻", schema)
        self.assertIn("探索间隔（分钟）", schema)
        self.assertFalse(cfg.plugin.enabled)
        self.assertFalse(cfg.drawing.enabled)
        self.assertEqual(cfg.budget.rounds, 3)
        for section in ["plugin", "explore", "models", "context", "sharing", "drawing", "budget", "memory"]:
            model = type(getattr(cfg, section))
            self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in model.__ui_label__))
            for name, field in model.model_fields.items():
                extra = field.json_schema_extra or {}
                self.assertIn("label", extra, (section, name))
                self.assertNotIn("?", extra["label"])
                self.assertNotEqual(extra["label"], name)
                if name != "config_version":
                    self.assertTrue(field.description, (section, name))
        self.assertTrue(type(cfg.plugin).model_fields["config_version"].json_schema_extra["hidden"])
