import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from voice_online_services import OnlineIntent, OnlineServices, parse_online_intent
from voice_text_pipeline import process_text


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


class OnlineIntentTests(unittest.TestCase):
    def test_weather_city_and_day_are_parsed(self):
        cases = {
            "今天天气怎么样": OnlineIntent("weather", city="杭州", day_offset=0),
            "问问天气": OnlineIntent("weather", city="杭州", day_offset=0),
            "上海明天天气": OnlineIntent("weather", city="上海", day_offset=1),
            "我想知道上海天气": OnlineIntent("weather", city="上海", day_offset=0),
            "后天北京气温多少": OnlineIntent("weather", city="北京", day_offset=2),
            "北京会下雨吗": OnlineIntent("weather", city="北京", day_offset=0),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_online_intent(text, default_city="杭州"), expected)

    def test_search_joke_and_song_are_parsed(self):
        self.assertEqual(
            parse_online_intent("搜索一下今天的科技新闻"),
            OnlineIntent("search", query="今天的科技新闻"),
        )
        self.assertEqual(parse_online_intent("给我讲个笑话"), OnlineIntent("joke"))
        self.assertEqual(parse_online_intent("唱首歌"), OnlineIntent("song"))
        self.assertIsNone(parse_online_intent("今天天气不错"))
        self.assertIsNone(parse_online_intent("开始按摩"))


class OnlineServicesTests(unittest.TestCase):
    @staticmethod
    def geocoding():
        return FakeResponse({
            "results": [{"name": "上海", "latitude": 31.23, "longitude": 121.47}]
        })

    @staticmethod
    def forecast():
        return FakeResponse({
            "current": {
                "temperature_2m": 28.5,
                "apparent_temperature": 30.0,
                "relative_humidity_2m": 65,
                "weather_code": 1,
                "wind_speed_10m": 8,
            },
            "daily": {
                "weather_code": [1, 61, 3],
                "temperature_2m_max": [32, 29, 27],
                "temperature_2m_min": [24, 23, 22],
                "precipitation_probability_max": [20, 70, 30],
            },
        })

    def test_current_weather_uses_geocoding_and_forecast(self):
        session = FakeSession(self.geocoding(), self.forecast())
        service = OnlineServices(session=session, enabled=True, timeout=3)
        result = service.handle(OnlineIntent("weather", city="上海"))
        self.assertIn("上海当前大致晴朗", result["reply"])
        self.assertIn("28.5度", result["reply"])
        self.assertIn("百分之20", result["reply"])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0][1]["timeout"], (5.0, 3.0))

    def test_tomorrow_weather_uses_daily_values(self):
        service = OnlineServices(
            session=FakeSession(self.geocoding(), self.forecast()),
            enabled=True,
        )
        reply = service.handle(OnlineIntent("weather", city="上海", day_offset=1))["reply"]
        self.assertIn("上海明天小雨", reply)
        self.assertIn("最低23度", reply)
        self.assertIn("百分之70", reply)

    def test_weather_network_failure_is_spoken_not_raised(self):
        service = OnlineServices(
            session=FakeSession(requests.ConnectionError("offline")),
            enabled=True,
        )
        result = service.handle(OnlineIntent("weather", city="上海"))
        self.assertIn("暂时不可用", result["reply"])

    def test_weather_malformed_provider_response_fails_closed(self):
        service = OnlineServices(
            session=FakeSession(FakeResponse({"results": ["bad-shape"]})),
            enabled=True,
        )
        result = service.handle(OnlineIntent("weather", city="上海"))
        self.assertIn("暂时不可用", result["reply"])

    def test_search_is_delegated_to_dify_without_local_network_call(self):
        session = FakeSession()
        service = OnlineServices(session=session, enabled=True)
        result = service.handle(OnlineIntent("search", query="机器人新闻"))
        self.assertIn("Dify模型处理", result["reply"])
        self.assertEqual(session.calls, [])

    def test_joke_and_song_do_not_need_network(self):
        service = OnlineServices(session=FakeSession(), enabled=False)
        self.assertIn("按摩机器人", service.handle(OnlineIntent("joke"))["reply"])
        song = service.handle(OnlineIntent("song"))["reply"]
        self.assertIn("原创歌", song)
        self.assertIn("普通语音", song)

    def test_pipeline_short_circuits_before_local_reply_and_dify(self):
        service = mock.Mock(default_city="上海")
        service.handle.return_value = {"reply": "上海当前晴朗，气温二十八度。"}
        speaker = mock.Mock()
        result = process_text(
            "上海今天天气怎么样",
            speaker=speaker,
            dialogue=lambda _text: (_ for _ in ()).throw(AssertionError("Dify called")),
            online_services=service,
        )
        self.assertEqual(result, [{"reply": "上海当前晴朗，气温二十八度。"}])
        service.handle.assert_called_once_with(OnlineIntent("weather", city="上海", day_offset=0))
        spoken = "".join(call.args[0] for call in speaker.call_args_list)
        self.assertIn("上海当前晴朗", spoken)

    def test_generic_search_is_delegated_to_dify_dialogue(self):
        service = mock.Mock(default_city="上海")
        calls = []

        def dialogue(text):
            calls.append(text)
            return [{"reply": "Dify模型原生联网结果。"}]

        result = process_text(
            "搜索一下机器人新闻",
            dialogue=dialogue,
            online_services=service,
        )
        self.assertEqual(result, [{"reply": "Dify模型原生联网结果。"}])
        self.assertEqual(calls, ["搜索一下机器人新闻"])
        service.handle.assert_not_called()

    def test_dify_search_failure_returns_clear_message_without_local_fallback(self):
        service = mock.Mock(default_city="上海")
        result = process_text(
            "搜索一下机器人新闻",
            dialogue=lambda _text: None,
            online_services=service,
        )
        self.assertEqual(result, [{
            "reply": "Dify模型联网搜索暂时不可用，请检查模型联网开关和工作流发布状态。"
        }])
        service.handle.assert_not_called()

    def test_service_close_closes_session(self):
        session = FakeSession()
        OnlineServices(session=session).close()
        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
