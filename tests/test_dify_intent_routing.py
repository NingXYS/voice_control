import json
import os
import unittest

import yaml


ROOT = os.path.dirname(os.path.dirname(__file__))


class DifyIntentRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(
            os.path.join(ROOT, "scripts", "voice_ros2_dify_v06.yml"),
            encoding="utf-8",
        ) as stream:
            cls.workflow = yaml.safe_load(stream)
        cls.nodes = {
            node["id"]: node
            for node in cls.workflow["workflow"]["graph"]["nodes"]
        }
        cls.edges = cls.workflow["workflow"]["graph"]["edges"]

    def test_intent_routing_is_local_and_distinguishes_common_requests(self):
        self.assertNotIn("normalize_intent", self.nodes)
        node = self.nodes["intent_classify"]
        self.assertEqual(node["data"]["type"], "code")
        scope = {}
        exec(node["data"]["code"], scope)

        for user_text, expected in (
            ("给我唱首歌", "fixed_reply"),
            ("今天天气怎么样", "web_search"),
            ("长春今天天气怎么样", "web_search"),
            ("北京明天会下雨吗", "web_search"),
            ("搜索一下今天的机器人新闻", "web_search"),
            ("联网查一下今天的科技新闻", "web_search"),
            ("查一下今天的科技新闻", "web_search"),
            ("左臂向下10厘米", "local_action"),
            ("左臂向上抬十厘米", "local_action"),
            ("左臂向上抬十五厘米", "local_action"),
            ("左臂关节1旋转三十度", "local_action"),
            ("右臂向前5厘米然后左臂向上10厘米", "control_action"),
            ("你能做什么右臂向上5厘米", "control_action"),
            ("请先说明坐标系再让左臂向上二十厘米", "control_action"),
            ("左臂向下", "ambiguous_control"),
            ("机器人的坐标系怎么定义", "robot_knowledge"),
            ("你有几个关节", "robot_knowledge"),
            ("你有几个自由度", "robot_knowledge"),
            ("有几条手臂", "robot_knowledge"),
            ("怎么记录按摩点位", "robot_knowledge"),
            ("方向接口完成了吗", "robot_knowledge"),
            ("今天是多少号", "web_search"),
            ("还有多少天国庆节", "web_search"),
            ("讲一个历史故事", "web_search"),
            ("为什么天空是蓝色的", "web_search"),
        ):
            with self.subTest(user_text=user_text):
                self.assertEqual(scope["main"](user_text), {"intent": expected})

        for case in self.nodes["route_by_intent"]["data"]["cases"]:
            selector = case["conditions"][0]["variable_selector"]
            self.assertEqual(selector, ["intent_classify", "intent"])

    def test_every_workflow_path_calls_at_most_one_llm(self):
        targets_by_source = {}
        for edge in self.edges:
            targets_by_source.setdefault(edge["source"], []).append(edge["target"])

        complete_paths = []
        pending_paths = [("start_voice_text", [])]
        while pending_paths:
            node_id, previous = pending_paths.pop()
            path = [*previous, node_id]
            targets = targets_by_source.get(node_id, [])
            if not targets:
                complete_paths.append(path)
                continue
            pending_paths.extend((target, path) for target in targets)

        for path in complete_paths:
            with self.subTest(path=path):
                llm_count = sum(
                    self.nodes[node_id]["data"]["type"] == "llm"
                    for node_id in path
                )
                self.assertLessEqual(llm_count, 1)

    def test_llm_nodes_limit_completion_budget(self):
        for node in self.nodes.values():
            if node["data"]["type"] != "llm":
                continue
            max_tokens = node["data"]["model"]["completion_params"]["max_tokens"]
            with self.subTest(node_id=node["id"]):
                self.assertLessEqual(max_tokens, 256)

    def test_web_search_uses_model_native_search_and_reply_only_guard(self):
        environment = self.workflow["workflow"]["environment_variables"]
        default_city = next(
            item for item in environment
            if item["name"] == "DEFAULT_WEATHER_CITY"
        )
        self.assertEqual(default_city["value"], "上海")
        self.assertEqual(default_city["value_type"], "string")
        self.assertFalse(any(
            node["data"]["type"] == "http-request"
            for node in self.nodes.values()
        ))

        search = self.nodes["llm_web_search_summary"]["data"]
        self.assertEqual(search["type"], "llm")
        self.assertTrue(search["model"]["completion_params"]["enable_search"])
        self.assertIn("通用知识问答", search["prompt_template"][0]["text"])
        self.assertIn("DEFAULT_WEATHER_CITY", search["prompt_template"][0]["text"])

        edge = next(
            edge for edge in self.edges
            if edge.get("sourceHandle") == "case_web_search"
        )
        self.assertEqual(edge["target"], "llm_web_search_summary")

        fallback_edge = next(
            edge for edge in self.edges
            if edge.get("sourceHandle") == "false"
        )
        self.assertEqual(fallback_edge["target"], "llm_web_search_summary")
        self.assertNotIn("tmpl_complex_fallback", self.nodes)

        guard_scope = {}
        exec(self.nodes["guard_web_search_reply"]["data"]["code"], guard_scope)
        guarded = guard_scope["main"](
            '{"action":"move_cartesian","arm":"left","z":0.1}'
        )
        parsed = json.loads(guarded["result"])
        self.assertEqual(set(parsed), {"reply"})
        self.assertNotIn("action", parsed)

    def test_fixed_reply_branch_is_deterministic_and_avoids_second_llm(self):
        self.assertNotIn("llm_fixed_reply", self.nodes)
        node = self.nodes["fixed_reply_local"]
        self.assertEqual(node["data"]["type"], "code")

        scope = {}
        exec(node["data"]["code"], scope)
        expected_needles = {
            "你是谁": ["小西", "单臂按摩机器人", "点位示教", "安全"],
            "自我介绍": ["按摩点位示教", "启动确认", "安全"],
            "强化学习": ["强化学习", "已示教点位"],
            "阻抗控制": ["力控参数", "下层机械臂程序"],
            "你能做什么": ["按摩点位", "启动按摩", "联网搜索", "尚未接入"],
            "你你会干什么": ["按摩点位", "启动按摩", "联网搜索", "尚未接入"],
            "给我唱首歌": ["普通语音", "原创歌"],
            "谢谢": ["不客气"],
        }
        for user_text, needles in expected_needles.items():
            with self.subTest(user_text=user_text):
                output = scope["main"](user_text)
                reply = json.loads(output["result"])["reply"]
                for needle in needles:
                    self.assertIn(needle, reply)

        edge = next(
            edge
            for edge in self.edges
            if edge.get("sourceHandle") == "case_fixed"
        )
        self.assertEqual(edge["target"], "fixed_reply_local")
        variables = self.nodes["merge_outputs"]["data"]["variables"]
        self.assertIn(["fixed_reply_local", "result"], variables)

    def test_simple_control_action_is_parsed_without_an_llm(self):
        node = self.nodes["local_action_parse"]
        self.assertEqual(node["data"]["type"], "code")
        scope = {}
        exec(node["data"]["code"], scope)

        for user_text, expected in (
            (
                "左臂向下10厘米",
                {
                    "action": "move_cartesian",
                    "arm": "left",
                    "x": 0.0,
                    "y": 0.0,
                    "z": -0.1,
                    "relative": True,
                },
            ),
            (
                "左臂向上抬十厘米",
                {
                    "action": "move_cartesian",
                    "arm": "left",
                    "x": 0.0,
                    "y": 0.0,
                    "z": 0.1,
                    "relative": True,
                },
            ),
            (
                "左臂向上抬十五厘米",
                {
                    "action": "move_cartesian",
                    "arm": "left",
                    "x": 0.0,
                    "y": 0.0,
                    "z": 0.15,
                    "relative": True,
                },
            ),
            (
                "左臂关节1旋转三十度",
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 1,
                    "value": 0.524,
                    "type": "delta",
                },
            ),
            (
                "左臂关节1旋转30度",
                {
                    "action": "move_joint",
                    "arm": "left",
                    "joint": 1,
                    "value": 0.524,
                    "type": "delta",
                },
            ),
            ("右臂回零位", {"action": "home", "arm": "right"}),
            ("查询左臂状态", {"action": "get_status", "arm": "left"}),
        ):
            with self.subTest(user_text=user_text):
                output = scope["main"](user_text)
                self.assertEqual(json.loads(output["result"]), expected)

        local_case = next(
            case
            for case in self.nodes["route_by_intent"]["data"]["cases"]
            if case["case_id"] == "case_local_action"
        )
        self.assertEqual(local_case["conditions"][0]["value"], "local_action")

    def test_local_action_parser_rejects_mixed_text(self):
        scope = {}
        exec(self.nodes["local_action_parse"]["data"]["code"], scope)

        for user_text in (
            "你能做什么右臂向上5厘米",
            "请先说明坐标系再让左臂向上二十厘米",
        ):
            with self.subTest(user_text=user_text):
                output = scope["main"](user_text)
                self.assertEqual(
                    json.loads(output["result"]),
                    {"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"},
                )

    def test_final_json_cleanup_strips_model_think_block(self):
        scope = {}
        exec(self.nodes["code_convert"]["data"]["code"], scope)
        raw = (
            "<think>用户询问能力，回答已知能力。</think>\n"
            '{"reply": "我可以控制左右两条机械臂，支持关节旋转和空间移动。"}'
        )

        result = scope["main"](raw)

        self.assertEqual(
            json.loads(result["result"]),
            [{"reply": "我可以控制左右两条机械臂，支持关节旋转和空间移动。"}],
        )


if __name__ == "__main__":
    unittest.main()
