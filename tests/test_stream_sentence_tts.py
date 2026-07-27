import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from voice_dialogue_backend import _delta_from_event, parse_output
from voice_text_pipeline import _looks_like_json_prefix, _speak_text, process_text
from voice_text_segmenter import StreamingTextSegmenter, split_sentences


class SegmenterTests(unittest.TestCase):
    def test_feed_emits_on_chinese_period(self):
        seg = StreamingTextSegmenter()
        self.assertEqual(seg.feed("你好"), [])
        self.assertEqual(seg.feed("世界。下一"), ["你好世界。"])
        self.assertEqual(seg.feed("句！"), ["下一句！"])
        self.assertEqual(seg.flush(), [])

    def test_flush_emits_tail(self):
        seg = StreamingTextSegmenter()
        seg.feed("还没有结束")
        self.assertEqual(seg.flush(), ["还没有结束"])

    def test_split_sentences(self):
        parts = split_sentences("第一句。第二句！第三句")
        self.assertEqual(parts, ["第一句。", "第二句！", "第三句"])


class DialogueEventTests(unittest.TestCase):
    def test_delta_from_text_chunk(self):
        self.assertEqual(
            _delta_from_event({"event": "text_chunk", "data": {"text": "你好"}}),
            "你好",
        )

    def test_delta_from_message_answer(self):
        self.assertEqual(
            _delta_from_event({"event": "message", "answer": "世界"}),
            "世界",
        )

    def test_parse_output_reply(self):
        self.assertEqual(
            parse_output('{"reply":"ok"}'),
            [{"reply": "ok"}],
        )


class PipelineStreamTests(unittest.TestCase):
    def test_json_prefix_detection(self):
        self.assertTrue(_looks_like_json_prefix('[{"action":"home"}]'))
        self.assertTrue(_looks_like_json_prefix('  {"reply":"x"}'))
        self.assertFalse(_looks_like_json_prefix("你好，我是机器人。"))

    def test_speak_text_splits_sentences(self):
        spoken = []
        with mock.patch.dict(os.environ, {"VOICE_SENTENCE_TTS": "1"}):
            _speak_text(spoken.append, "第一句。第二句。")
        self.assertEqual(spoken, ["第一句。", "第二句。"])

    def test_stream_dialogue_sentence_tts(self):
        spoken = []

        class FakeDialogue:
            def stream_reply(self, text):
                yield ("delta", "机械臂有")
                yield ("delta", "两条手臂。")
                yield ("delta", "每条六个关节。")
                yield ("done", [{"reply": "机械臂有两条手臂。每条六个关节。"}])

            def run(self, text):
                raise AssertionError("blocking run should not be used")

        with mock.patch.dict(
            os.environ,
            {
                "VOICE_STREAM_REPLY": "1",
                "VOICE_SENTENCE_TTS": "1",
                "VOICE_THINKING_ACK": "0",
            },
        ):
            result = process_text(
                "请详细介绍一下展览上的新产品功能特点",
                speaker=spoken.append,
                dialogue=FakeDialogue(),
            )
        self.assertIsNotNone(result)
        # Thinking disabled; streamed sentences should have been spoken.
        self.assertTrue(any("手臂" in s for s in spoken))
        self.assertTrue(any("关节" in s for s in spoken))


if __name__ == "__main__":
    unittest.main()
