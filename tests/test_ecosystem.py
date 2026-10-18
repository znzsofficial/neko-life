"""Isolated three-plugin protocol test. Requires adjacent source checkouts + SDK."""

import importlib
from contextlib import AsyncExitStack
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[2]
AVAILABLE = (
    importlib.util.find_spec("maibot_sdk")
    and (ROOT / "neko-web/plugin.py").exists()
    and (ROOT / "attention-seeker-mai/plugin.py").exists()
)


def package(name, directory):
    module = types.ModuleType(name)
    module.__path__ = [str(directory)]
    sys.modules[name] = module
    return importlib.import_module(name + ".plugin")


@unittest.skipUnless(AVAILABLE, "adjacent plugin snapshots and real SDK required")
class EcosystemTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(
        (ROOT / "neko-draw/plugin.py").exists() and (ROOT / "neko-tts/history_visibility.py").exists(),
        "adjacent draw/TTS source snapshots required",
    )
    async def test_draw_and_tts_hooks_preserve_life_context_without_spending(self):
        from neko_life.context import inject

        draw_module = package("ecosystem_draw", ROOT / "neko-draw")
        visibility_spec = importlib.util.spec_from_file_location(
            "life_tts_visibility", ROOT / "neko-tts/history_visibility.py"
        )
        visibility_module = importlib.util.module_from_spec(visibility_spec)
        visibility_spec.loader.exec_module(visibility_module)

        class Draw(draw_module.NekoDraw):
            config = draw_module.PluginConfig()
            ctx = types.SimpleNamespace(logger=Mock())

        draw = Draw()
        media = {
            "item_type": "UserMessageItem",
            "parts": [
                {"type": "text", "text": "画一张你在读书的自画像"},
                {"type": "image", "image_format": "png", "image_base64": "synthetic"},
            ],
        }
        items = inject([media], "角色生活设定：阅读；不是现实证据。不授权自主配图。")
        result = await draw.configure_planner(session_id="chat", items=items)
        updated = result["modified_kwargs"]["items"] if result else items
        self.assertIn("query_memory", json.dumps(updated, ensure_ascii=False))
        self.assertEqual(updated[0], media)
        filtered = visibility_module.VoiceVisibility().filter_items(updated, "chat")
        self.assertEqual(filtered, updated)
        self.assertFalse(draw._runners)

    async def test_authenticated_exploration_and_share_receipt_without_network_or_qq(self):
        from neko_life.plugin import NekoLifePlugin
        from neko_life.config import Settings
        from neko_life.exploration import Explorer
        from neko_life.bridge import WebBridge
        from neko_life.models import ModelService

        web = package("ecosystem_web", ROOT / "neko-web")
        proactive = package("ecosystem_proactive", ROOT / "attention-seeker-mai")
        async with AsyncExitStack() as cleanup:
            directory = cleanup.enter_context(tempfile.TemporaryDirectory())
            root = Path(directory)
            for name in ["web", "life", "proactive"]:
                (root / name).mkdir()
            key, share_key = "67" * 32, "78" * 32
            for file, payload in [
                (root / "web/automation-keys.json", {"neko.life": key}),
                (root / "life/web-client.json", {"neko.life": key}),
                (root / "life/sharing-keys.json", {"attention-seeker-mai": share_key}),
                (root / "proactive/life-client.json", {"attention-seeker-mai": share_key}),
            ]:
                file.write_text(json.dumps(payload), encoding="utf-8")
                file.chmod(0o600)

            class Web(web.NekoWebPlugin):
                config = web.NekoWebPluginConfig()
                ctx = types.SimpleNamespace(
                    paths=types.SimpleNamespace(data_dir=str(root / "web")), logger=Mock()
                )

            class Life(NekoLifePlugin):
                config = Settings()
                ctx = types.SimpleNamespace(
                    paths=types.SimpleNamespace(data_dir=str(root / "life")),
                    logger=Mock(),
                    config=types.SimpleNamespace(get=AsyncMock(return_value="合成角色")),
                )

            w, life = Web(), Life()
            w.config.plugin.enabled = True
            w.config.automation.enabled = True
            await w.on_load()
            await life.on_load()
            cleanup.push_async_callback(w.on_unload)
            cleanup.push_async_callback(life.on_unload)

            async def fake_retrieval(kind, arguments):
                if kind == "search":
                    return {
                        "success": True,
                        "status": "ok",
                        "results": [
                            {
                                "title": "公开科学资料",
                                "url": "https://source.example/a",
                                "snippet": "公开摘要",
                            }
                        ],
                    }
                return {
                    "success": True,
                    "status": "ok",
                    "documents": [
                        {
                            "title": "公开科学资料",
                            "url": "https://source.example/a",
                            "text": "供测试的公开文章正文",
                        }
                    ],
                }

            w._automation_execute = fake_retrieval

            async def web_call(capability, **kwargs):
                self.assertEqual(capability, "api.call")
                self.assertEqual(kwargs["api_name"], "neko.web.automation_v1")
                from maibot_sdk.context import PluginContext

                envelope = {"success": True, "result": await w.automation_v1(**kwargs["args"])}
                return PluginContext._normalize_capability_result("api.call", envelope)

            life.ctx.call_capability = web_call
            life.ctx.llm = types.SimpleNamespace(
                generate=AsyncMock(
                    side_effect=[
                        {
                            "success": True,
                            "response": json.dumps({"topic": "天文发现", "query": "近期天文公开研究"}),
                            "prompt_tokens": 200,
                            "completion_tokens": 80,
                        },
                        {
                            "success": True,
                            "prompt_tokens": 500,
                            "completion_tokens": 120,
                            "response": json.dumps(
                                {
                                    "worth_saving": True,
                                    "summary": "公开发现尚需验证。",
                                    "opinion": "值得关注",
                                    "source_indexes": [0],
                                    "open_questions": [],
                                }
                            ),
                        },
                    ]
                )
            )
            model = ModelService(life.ctx, life.store, life.persona, True)
            explorer = Explorer(
                life.store, model, WebBridge(life.ctx, root / "life/web-client.json"), life.persona, ["天文"]
            )
            self.assertEqual(await explorer.run(), "saved")
            life.config.plugin.enabled = True
            life.config.sharing.enabled = True
            life.config.sharing.sessions = ["chat"]

            async def share_call(capability, **kwargs):
                self.assertEqual(kwargs["api_name"], "neko.life.sharing_v1")
                from maibot_sdk.context import PluginContext

                envelope = {"success": True, "result": await life.sharing_api(**kwargs["args"])}
                return PluginContext._normalize_capability_result("api.call", envelope)

            task = "proactive:attention-seeker-mai:1700000000000"

            class Proactive(proactive.LonelyMaiPlugin):
                config = proactive.LonelyMaiConfig()
                ctx = types.SimpleNamespace(
                    paths=types.SimpleNamespace(data_dir=str(root / "proactive")),
                    logger=Mock(),
                    call_capability=share_call,
                    maisaka=types.SimpleNamespace(
                        proactive=types.SimpleNamespace(
                            trigger=AsyncMock(return_value={"success": True, "task_id": task})
                        )
                    ),
                )

            bot = Proactive()
            bot.config.life.enabled = True
            state = proactive.ChatStreamState("chat", "synthetic")
            self.assertTrue(await bot._do_proactive_chat(state, "synthetic"))
            kwargs = bot.ctx.maisaka.proactive.trigger.call_args.kwargs
            self.assertIn("公开发现", kwargs["reason"])
            self.assertEqual(kwargs["metadata"]["source"], "lonelymai")
            self.assertEqual(kwargs["intent"], bot.config.intent.private_text)
            rows = bot._life._read()
            receipt = next(iter(rows))
            self.assertEqual(rows[receipt]["status"], "submitted")
            await bot.life_after_send(
                message={"session_id": "chat"}, reply_message_id="real-qq-anchor", sent=True
            )
            self.assertEqual(bot._life._read()[receipt]["status"], "submitted")
            await bot.life_after_send(message={"session_id": "chat"}, reply_message_id=task, sent=True)
            self.assertEqual(bot._life._read()[receipt]["status"], "sent")
            self.assertIsNone(await life.store.call("claim", life.persona, "chat"))
