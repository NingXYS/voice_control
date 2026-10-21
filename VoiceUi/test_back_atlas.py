"""图示的静态资源白名单和现有 UI 接口回归；不启动语音或机器人。"""
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest

from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from voice_ui_server import build_app


class AtlasMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.images = []

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if "id" in values: self.ids.append(values["id"])
        if tag == "image": self.images.append(values.get("href"))


class BackAtlasTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(build_app(token="atlas-test-token-123456789")))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_assets_have_expected_type_and_existing_csp(self):
        for path, kind in (("/back-atlas.css", "text/css"), ("/back-torso-sage.png", "image/png")):
            response = await self.client.get(path)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, kind)
            self.assertIn("img-src 'self'", response.headers["Content-Security-Policy"])
            self.assertIn("style-src 'self'", response.headers["Content-Security-Policy"])
            body = await response.read()
            self.assertTrue(body)
            if kind == "image/png": self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))

    async def test_eight_names_accessible_and_before_conversation(self):
        body = await (await self.client.get("/")).text()
        for name in ("大椎", "肺俞", "心俞", "膈俞", "肝俞", "脾俞", "肾俞", "腰阳关"):
            self.assertIn(name, body)
        parser = AtlasMarkup()
        parser.feed(body)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertLess(parser.ids.index("backPanel"), parser.ids.index("conversation"))
        self.assertIn("/back-torso-sage.png", parser.images)
        self.assertIn('aria-labelledby="backAtlasTitle backAtlasDescription"', body)
        self.assertIn('id="stopBtn"', body)
        self.assertIn('id="forcePanel"', body)

    async def test_new_resources_do_not_expose_config_or_relax_api_auth(self):
        for path in ("/force_bridge.env", "/assets/force_bridge.env", "/api/force/history", "/back-atlas.css.bak"):
            response = await self.client.get(path)
            self.assertIn(response.status, (401, 404))
        response = await self.client.post("/api/runtime/start")
        self.assertEqual(response.status, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
