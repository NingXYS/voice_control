"""认证输入边界回归；不启动音频设备或机械臂。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
from voice_ui_server import _constant_time_text_equal, build_app

TOKEN = "test-auth-input-token-20261019"


class TextComparisonTests(unittest.TestCase):
    def test_exact_utf8_comparison_and_invalid_types(self):
        self.assertTrue(_constant_time_text_equal("中文令牌", "中文令牌"))
        self.assertFalse(_constant_time_text_equal("中文", TOKEN))
        self.assertFalse(_constant_time_text_equal("ＡＢＣ", "ABC"))
        self.assertFalse(_constant_time_text_equal("\ud800", TOKEN))
        for value in (None, 123, True, {}, []):
            self.assertFalse(_constant_time_text_equal(value, TOKEN))


class AuthInputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(build_app(token=TOKEN)),
                                 cookie_jar=aiohttp.CookieJar(unsafe=True))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_nonascii_and_invalid_token_values_return_401_then_valid_token_works(self):
        for token in ("请输入令牌", "🔑", "ＡＢＣ", "\ud800", None, 123, True, {}, []):
            with self.subTest(kind=type(token).__name__):
                response = await self.client.post("/api/auth", json={"token": token})
                self.assertEqual(response.status, 401)
                self.assertIn("令牌错误", await response.text())
                self.assertIn("Content-Security-Policy", response.headers)
                valid = await self.client.post("/api/auth", json={"token": TOKEN})
                self.assertEqual(valid.status, 200)
                self.assertTrue((await valid.json())["csrf_token"])

    async def test_nonobject_and_malformed_json_are_rejected_normally(self):
        for body in ('["token"]', '"token"', 'null', '{broken'):
            response = await self.client.post("/api/auth", data=body, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status, 401)

    async def test_unicode_errors_still_count_toward_rate_limit(self):
        for _ in range(5):
            self.assertEqual((await self.client.post("/api/auth", json={"token": "错误令牌"})).status, 401)
        self.assertEqual((await self.client.post("/api/auth", json={"token": "错误令牌"})).status, 429)

    async def test_nonascii_csrf_header_returns_403(self):
        await self.client.post("/api/auth", json={"token": TOKEN})
        response = await self.client.post("/api/conversation/clear", headers={"X-CSRF-Token": "错误令牌"})
        self.assertEqual(response.status, 403)

    async def test_nonascii_origin_returns_403(self):
        client = TestClient(TestServer(build_app(token=TOKEN, public_origin="https://voice.example.com")))
        await client.start_server()
        try:
            response = await client.post("/api/auth", json={"token": TOKEN}, headers={"Origin": "https://错误.example.com"})
            self.assertEqual(response.status, 403)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
