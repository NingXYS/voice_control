#!/usr/bin/env python3
# noqa: SIZE_OK — Dify 生成器需要在同一文件内保存嵌入代码、提示词和声明式工作流图。
"""生成 Dify Workflow DSL v0.6.0 YAML 文件（含条件分支后置的知识库检索）"""
import uuid
from pathlib import Path
import yaml

WF_ID = str(uuid.uuid4())

LOCAL_INTENT_CODE = """import re

def main(user_text: str) -> dict:
    text = re.sub(r'[\\s，。！？；：,.!?;:]+', '', user_text or '')
    arms = re.findall(r'左臂|右臂|左手|右手', text)
    directions = re.findall(r'向上|向下|向前|向后|向左|向右', text)
    distances = re.findall(r'-?\\d+(?:\\.\\d+)?(?:毫米|厘米|米)', text)
    joints = re.findall(r'关节[1-6]', text)
    angles = re.findall(r'-?\\d+(?:\\.\\d+)?(?:度|弧度)', text)
    has_home = any(keyword in text for keyword in ('回零', '归零', '零位'))
    has_status = '状态' in text or ('查询' in text and '位置' in text)
    is_simple = bool(arms) and (
        bool(directions and distances)
        or bool(joints and angles)
        or has_home
        or has_status
    )
    is_composite = (
        len(arms) > 1
        or len(directions) > 1
        or len(joints) > 1
        or any(keyword in text for keyword in ('然后', '同时', '并且', '接着', '再把', '再将'))
    )
    if is_simple:
        return {'intent': 'control_action' if is_composite else 'local_action'}
    if any(keyword in text for keyword in ('有什么限制', '支持哪些关节', '移动多远', '坐标系', '怎么下达指令', '指令格式', '指令要求', '机械臂可以', '抓取', '拿东西', '放东西', '能旋转', '可以旋转')):
        return {'intent': 'robot_knowledge'}
    if any(keyword in text for keyword in ('你是谁', '你叫什么', '你是什么', '介绍', '你能做什么', '你会做什么', '你会干什么', '你能干什么', '功能', '你好', '您好', '谢谢', '感谢', '辛苦了', '唱歌', '唱首歌', '唱一首', '跳舞', '天气', '气温', '下雨', '联网', '上网', '在线检索')):
        return {'intent': 'fixed_reply'}
    if any(keyword in text for keyword in ('左臂', '右臂', '左手', '右手', '关节', '移动', '向上', '向下', '向前', '向后', '向左', '向右', '抬', '降', '旋转', '转动', '回零', '归零', '状态', '位置')):
        return {'intent': 'ambiguous_control'}
    return {'intent': 'complex_fallback'}"""

FIXED_REPLY_CODE = """import json
import re

def main(user_text: str) -> dict:
    text = re.sub(r'[\\s，。！？；：,.!?;:]+', '', user_text or '')
    if any(keyword in text for keyword in ('唱歌', '唱首歌', '唱一首', '跳舞')):
        reply = '我不能唱歌。我可以控制左右两条机械臂，支持关节旋转和空间移动。'
    elif any(keyword in text for keyword in ('天气', '气温', '下雨')):
        reply = '我无法查询天气。我可以帮助控制左右两条机械臂。'
    elif any(keyword in text for keyword in ('联网', '上网', '在线检索')):
        reply = '我不能联网检索。我可以帮助控制左右两条机械臂。'
    elif any(keyword in text for keyword in ('你能做什么', '你会做什么', '你会干什么', '你能干什么', '你有什么功能', '你支持哪些指令', '你能控制什么', '你支持哪些动作', '功能')):
        reply = '我可以控制左右两条机械臂，支持关节旋转和空间移动。'
    elif any(keyword in text for keyword in ('你是谁', '你叫什么', '你是什么', '介绍一下自己', '介绍自己', '介绍一下你', '自我介绍', '介绍你')):
        reply = '我是施耐力双臂六关节机械臂，拥有左右两条手臂，各六个关节。'
    elif any(keyword in text for keyword in ('谢谢', '感谢', '辛苦了')):
        reply = '不客气，很高兴能帮到你。'
    else:
        reply = '你好！我是机械臂控制助手，请问有什么可以帮您？'
    return {'result': json.dumps({'reply': reply}, ensure_ascii=False)}"""

LOCAL_ACTION_CODE = """import json
import math
import re

def main(user_text: str) -> dict:
    text = re.sub(r'[\\s，。！？；：,.!?;:]+', '', user_text or '')
    arm_match = re.search(r'左臂|左手|右臂|右手', text)
    if arm_match is None:
        return {'result': json.dumps({'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}, ensure_ascii=False)}
    arm = 'left' if arm_match.group(0) in ('左臂', '左手') else 'right'
    if any(keyword in text for keyword in ('回零', '归零', '零位')):
        command = {'action': 'home', 'arm': arm}
    elif '状态' in text or ('查询' in text and '位置' in text):
        command = {'action': 'get_status', 'arm': arm}
    else:
        joint_match = re.search(r'关节([1-6])', text)
        angle_match = re.search(r'(-?\\d+(?:\\.\\d+)?)(度|弧度)', text)
        direction_match = re.search(r'向上|向下|向前|向后|向左|向右', text)
        distance_match = re.search(r'(-?\\d+(?:\\.\\d+)?)(毫米|厘米|米)', text)
        if joint_match is not None and angle_match is not None:
            value = float(angle_match.group(1))
            if angle_match.group(2) == '度':
                value = math.radians(value)
            if value > 0 and any(keyword in text for keyword in ('反转', '反向')):
                value = -value
            command = {
                'action': 'move_joint',
                'arm': arm,
                'joint': int(joint_match.group(1)),
                'value': round(value, 3),
                'type': 'delta',
            }
        elif direction_match is not None and distance_match is not None:
            distance = float(distance_match.group(1))
            scale = {'毫米': 0.001, '厘米': 0.01, '米': 1.0}[distance_match.group(2)]
            value = round(distance * scale, 6)
            direction = direction_match.group(0)
            x, y, z = 0.0, 0.0, 0.0
            if direction == '向右':
                x = value
            elif direction == '向左':
                x = -value
            elif direction == '向前':
                y = value
            elif direction == '向后':
                y = -value
            elif direction == '向上':
                z = value
            else:
                z = -value
            command = {
                'action': 'move_cartesian',
                'arm': arm,
                'x': x,
                'y': y,
                'z': z,
                'relative': True,
            }
        else:
            command = {'reply': '请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。'}
    return {'result': json.dumps(command, ensure_ascii=False)}"""

# 动作解析 Prompt
CONTROL_ACTION_PROMPT = """你是双臂机械臂控制助手，负责将用户的自然语言指令转换为JSON。

【输出 Schema 定义 - 严格遵循】
只支持以下五种输出类型，字段与类型必须完全匹配，不得混用或缺少：
1. reply：只用于澄清和说明，不能包含 action 字段。
   {"reply": "回复内容"}
2. move_cartesian：笛卡尔空间直线运动。
   {"action": "move_cartesian", "arm": "left|right", "x": 0.0, "y": 0.0, "z": 0.0, "relative": true}
3. move_joint：关节空间相对或绝对旋转。
   {"action": "move_joint", "arm": "left|right", "joint": 1, "value": 0.0, "type": "delta|absolute"}
4. home：回零位。
   {"action": "home", "arm": "left|right"}
5. get_status：查询状态。
   {"action": "get_status", "arm": "left|right"}

【Python 校验合约】
- reply 和 action 字段绝对不得同时存在。
- arm 只能是 "left" 或 "right"。
- home 和 get_status 必须显式指定合法的 arm 字段，不得默认左臂或右臂。
- home 和 get_status 严禁且不需要补 joint, value, type, x, y, z, relative 等任何运动相关字段。

【指令类型判断规则】
- 用户要求控制机械臂动作（位移、旋转、回零、查询状态等）且参数齐全 → 输出动作/控制类型（带 action 字段）。
- 用户指令缺少手臂、动作、方向、距离、关节编号或角度等关键信息 → 输出澄清型 reply。

【动作类型选择规则】
- 用户提到"关节""旋转""转动" → action: "move_joint"
- 用户提到"上下左右前后""移动""走""抬""降" → action: "move_cartesian"
- 用户提到"回零""回零位""归零" → action: "home"
- 用户提到"查询""状态""位置" → action: "get_status"

【坐标系与单位换算】
- 距离：厘米必须换算为米（例如：10厘米=0.1米，5厘米=0.05米）。
- 角度：度必须换算为弧度（例如：30度≈0.524弧度，45度≈0.785弧度）。
- 坐标方向：向右为 x 正，向左为 x 负；向前为 y 正，向后为 y 负；向上为 z 正，向下为 z 负。
- relative 对于 move_cartesian 始终为 true。
- 未说"反转"或"反向"时，move_joint 的 value 为正数；当且仅当手臂、关节和角度明确时，type 使用 "delta"。

【安全澄清与防默认规则】
- 必须防止高风险默认行为：严禁出现“未指定距离默认移动 0.05米”或“未指定角度默认旋转 0.1弧度”等无条件默认执行动作规则！
- 对于任何缺少手臂（如未指明是左臂还是右臂）、未指明运动方向、距离、关节编号或旋转角度等模糊输入，绝对不允许猜测并默认执行任何动作，必须输出统一的澄清型回复。
- 澄清回复统一文案为："请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"
- 缺关键字段的输入如“左臂向上”、“右臂向前”、“左臂关节1旋转”、“回零”、“查询状态”等，必须输出澄清回复，禁止生成动作 JSON 默认执行。

【能力边界约束】
- 本系统仅支持左右臂在三维空间移动和关节旋转。
- 不得对用户承诺任何未实现的能力，例如：抓取、松开、拿、放、联网检索、云服务、物体识别或其它真实物理外设操控。

【示例 - 安全澄清】
用户：抬起你的左手
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

用户：左臂向上
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

用户：查询状态
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

用户：回零
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

【示例 - 明确动作】
用户：左臂向上10厘米
输出：{"action": "move_cartesian", "arm": "left", "x": 0.0, "y": 0.0, "z": 0.1, "relative": true}

用户：右臂向前5厘米
输出：{"action": "move_cartesian", "arm": "right", "x": 0.0, "y": 0.05, "z": 0.0, "relative": true}

用户：左臂关节1旋转30度
输出：{"action": "move_joint", "arm": "left", "joint": 1, "value": 0.524, "type": "delta"}

用户：右臂回零位
输出：{"action": "home", "arm": "right"}

用户：查询左臂状态
输出：{"action": "get_status", "arm": "left"}

【示例 - 混合/组合指令】
用户：你是什么机器人然后右臂向上5厘米 （注：由于问答部分由前置意图分类处理，此处仅处理动作）
输出：{"action": "move_cartesian", "arm": "right", "x": 0.0, "y": 0.0, "z": 0.05, "relative": true}

用户：右臂向前5厘米左臂向上10厘米
输出：[{"action": "move_cartesian", "arm": "right", "x": 0.0, "y": 0.05, "z": 0.0, "relative": true}, {"action": "move_cartesian", "arm": "left", "x": 0.0, "y": 0.0, "z": 0.1, "relative": true}]

用户：左臂关节3反转30度
输出：{"action": "move_joint", "arm": "left", "joint": 3, "value": -0.524, "type": "delta"}

用户：左臂向上右臂向前再左臂向右 （注：由于没有距离，且属于混合动作，输出澄清）
输出：{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}

【输出约束】
- 只输出纯 JSON 字符串，绝不包含任何 markdown 代码块标识（如 ```json 等）或多余的自然语言解释。
- 单个指令返回 JSON 对象，多条或复合意图返回 JSON 数组，保持用户说话顺序。"""

# 知识问答 Prompt
ROBOT_KNOWLEDGE_PROMPT = """你是施耐力双臂六关节机械臂控制助手。请根据知识库检索到的相关指令修正与问答信息，结合用户的输入进行准确、简短、礼貌的回答。

【知识库参考 - 优先遵循】
以下是从知识库检索到的相关参考信息：
{{#knowledge_retrieve.result#}}

【限制与约束】
- 你的回答必须是合法的 JSON 对象，且仅包含 reply 字段，例如：
  {"reply": "回答内容"}
- 你的回复应当简短、直截了当、适合语音合成 (TTS)。
- 绝对不要输出任何 markdown 格式（如 ```json 等）、额外文字或标点符号。
- 本系统目前仅支持控制左右臂在三维空间内直线移动（空间移动）、六个关节的相对或绝对旋转（关节旋转）、回到零位（回零）以及查询当前位置与关节状态。
- 严禁承诺任何未实现的能力，例如：抓取物品、松开物品、拿东西、放东西、物体识别、联网检索、云服务等。
- 如果用户询问了非本系统支持的问题，或知识库没有相关信息，请礼貌地予以澄清并告知支持的指令范围。"""

CODE_NODE_CODE = """import json
import re

def main(raw_json: str) -> dict:
    result = re.sub(r'<think>.*?</think>', '', raw_json, flags=re.DOTALL | re.IGNORECASE).strip()
    if result.startswith('```json'):
        result = result[7:]
    elif result.startswith('```'):
        result = result[3:]
    if result.endswith('```'):
        result = result[:-3]
    result = result.strip()
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        fixed = re.sub(r'\\}\\s*,\\s*\\{', '},{', result)
        try:
            parsed = json.loads('[' + fixed + ']')
        except json.JSONDecodeError:
            return {'result': json.dumps([], ensure_ascii=False)}
    if isinstance(parsed, dict):
        parsed = [parsed]
    elif not isinstance(parsed, list):
        parsed = []
    return {'result': json.dumps(parsed, ensure_ascii=False)}"""

dsl = {
    "version": "0.6.0",
    "kind": "app",
    "app": {
        "name": "语音指令→ROS2命令",
        "description": "将语音识别的自然语言指令解析为ROS2机械臂控制JSON命令（条件分支后置知识库）",
        "mode": "workflow",
        "icon_type": "emoji",
        "icon": "🤖",
        "icon_background": "#FFEAD5",
    },
    "workflow": {
        "id": WF_ID,
        "title": "语音指令解析工作流(知识库)",
        "features": {
            "file_upload": {
                "enabled": False,
                "image": {"enabled": False}
            }
        },
        "conversation_variables": [],
        "environment_variables": [],
        "graph": {
            "nodes": [
                {
                    "id": "start_voice_text",
                    "data": {
                        "type": "start",
                        "title": "开始",
                        "variables": [
                            {
                                "variable": "text",
                                "label": "语音文本",
                                "type": "text-input",
                                "required": True,
                                "max_length": 512,
                                "default": ""
                            }
                        ]
                    },
                    "position": {"x": 50, "y": 200},
                },
                {
                    "id": "intent_classify",
                    "data": {
                        "type": "code",
                        "title": "本地意图分类",
                        "description": "规则分类，不调用模型",
                        "code_language": "python3",
                        "code": LOCAL_INTENT_CODE,
                        "variables": [
                            {"variable": "user_text", "value_selector": ["start_voice_text", "text"]}
                        ],
                        "outputs": {"intent": {"type": "string"}}
                    },
                    "position": {"x": 250, "y": 200},
                },
                {
                    "id": "route_by_intent",
                    "data": {
                        "type": "if-else",
                        "title": "意图路由",
                        "cases": [
                            {
                                "case_id": "case_fixed",
                                "logical_operator": "and",
                                "conditions": [
                                    {
                                        "id": "cond_fixed",
                                        "variable_selector": ["intent_classify", "intent"],
                                        "comparison_operator": "is",
                                        "value": "fixed_reply"
                                    }
                                ]
                            },
                            {
                                "case_id": "case_local_action",
                                "logical_operator": "and",
                                "conditions": [
                                    {
                                        "id": "cond_local_action",
                                        "variable_selector": ["intent_classify", "intent"],
                                        "comparison_operator": "is",
                                        "value": "local_action"
                                    }
                                ]
                            },
                            {
                                "case_id": "case_control",
                                "logical_operator": "and",
                                "conditions": [
                                    {
                                        "id": "cond_control",
                                        "variable_selector": ["intent_classify", "intent"],
                                        "comparison_operator": "is",
                                        "value": "control_action"
                                    }
                                ]
                            },
                            {
                                "case_id": "case_ambiguous",
                                "logical_operator": "and",
                                "conditions": [
                                    {
                                        "id": "cond_ambiguous",
                                        "variable_selector": ["intent_classify", "intent"],
                                        "comparison_operator": "is",
                                        "value": "ambiguous_control"
                                    }
                                ]
                            },
                            {
                                "case_id": "case_knowledge",
                                "logical_operator": "and",
                                "conditions": [
                                    {
                                        "id": "cond_knowledge",
                                        "variable_selector": ["intent_classify", "intent"],
                                        "comparison_operator": "is",
                                        "value": "robot_knowledge"
                                    }
                                ]
                            }
                        ]
                    },
                    "position": {"x": 450, "y": 200},
                },
                {
                    "id": "fixed_reply_local",
                    "data": {
                        "type": "code",
                        "title": "本地固定问答",
                        "description": "确定性本地回复，不调用模型",
                        "code_language": "python3",
                        "code": FIXED_REPLY_CODE,
                        "variables": [
                            {"variable": "user_text", "value_selector": ["start_voice_text", "text"]}
                        ],
                        "outputs": {"result": {"type": "string"}}
                    },
                    "position": {"x": 700, "y": 0},
                },
                {
                    "id": "local_action_parse",
                    "data": {
                        "type": "code",
                        "title": "本地动作解析",
                        "description": "解析常见单条明确动作，不调用模型",
                        "code_language": "python3",
                        "code": LOCAL_ACTION_CODE,
                        "variables": [
                            {"variable": "user_text", "value_selector": ["start_voice_text", "text"]}
                        ],
                        "outputs": {"result": {"type": "string"}}
                    },
                    "position": {"x": 700, "y": 100},
                },
                {
                    "id": "llm_control_action",
                    "data": {
                        "type": "llm",
                        "title": "动作指令解析",
                        "description": "解析明确的机械臂动作控制指令",
                        "context": {"enabled": False},
                        "model": {
                            "mode": "chat",
                            "provider": "",
                            "name": "",
                            "completion_params": {
                                "temperature": 0.1,
                                "max_tokens": 256,
                                "top_p": 0.95,
                                "stop": []
                            }
                        },
                        "prompt_template": [
                            {"role": "system", "text": CONTROL_ACTION_PROMPT},
                            {"role": "user", "text": "{{#start_voice_text.text#}}"}
                        ],
                        "variables": []
                    },
                    "position": {"x": 700, "y": 150},
                },
                {
                    "id": "tmpl_ambiguous_control",
                    "data": {
                        "type": "template-transform",
                        "title": "模糊指令澄清",
                        "template": '{"reply": "请说明左臂还是右臂，以及具体动作、方向、距离或关节角度。"}',
                        "variables": []
                    },
                    "position": {"x": 700, "y": 300},
                },
                {
                    "id": "knowledge_retrieve",
                    "data": {
                        "type": "knowledge-retrieval",
                        "title": "知识库检索",
                        "description": "从知识库中检索与机器人相关的说明信息",
                        "query_variable_selector": ["start_voice_text", "text"],
                        "dataset_ids": [],
                        "retrieval_mode": "multiple",
                        "top_k": 3,
                        "score_threshold": 0.5
                    },
                    "position": {"x": 700, "y": 450},
                },
                {
                    "id": "llm_robot_knowledge",
                    "data": {
                        "type": "llm",
                        "title": "知识问答回复",
                        "description": "结合知识库检索结果进行回复",
                        "context": {"enabled": False},
                        "model": {
                            "mode": "chat",
                            "provider": "",
                            "name": "",
                            "completion_params": {
                                "temperature": 0.1,
                                "max_tokens": 256,
                                "top_p": 0.95,
                                "stop": []
                            }
                        },
                        "prompt_template": [
                            {"role": "system", "text": ROBOT_KNOWLEDGE_PROMPT},
                            {"role": "user", "text": "{{#start_voice_text.text#}}"}
                        ],
                        "variables": []
                    },
                    "position": {"x": 920, "y": 450},
                },
                {
                    "id": "tmpl_complex_fallback",
                    "data": {
                        "type": "template-transform",
                        "title": "复杂兜底澄清",
                        "template": '{"reply": "这个问题不属于机械臂控制范围。我可以回答机械臂能力并处理明确的控制指令。"}',
                        "variables": []
                    },
                    "position": {"x": 700, "y": 600},
                },
                {
                    "id": "merge_outputs",
                    "data": {
                        "type": "variable-aggregator",
                        "title": "合并分支输出",
                        "output_type": "string",
                        "variables": [
                            ["fixed_reply_local", "result"],
                            ["local_action_parse", "result"],
                            ["llm_control_action", "text"],
                            ["tmpl_ambiguous_control", "output"],
                            ["llm_robot_knowledge", "text"],
                            ["tmpl_complex_fallback", "output"]
                        ]
                    },
                    "position": {"x": 1150, "y": 250},
                },
                {
                    "id": "code_convert",
                    "data": {
                        "type": "code",
                        "title": "JSON验证与清理",
                        "description": "验证LLM输出的JSON并确保格式正确",
                        "code_language": "python3",
                        "code": CODE_NODE_CODE,
                        "variables": [
                            {"variable": "raw_json", "value_selector": ["merge_outputs", "output"]}
                        ],
                        "outputs": {"result": {"type": "string"}}
                    },
                    "position": {"x": 1350, "y": 250},
                },
                {
                    "id": "end_result",
                    "data": {
                        "type": "end",
                        "title": "输出",
                        "outputs": [
                            {"variable": "result", "value_selector": ["code_convert", "result"]}
                        ]
                    },
                    "position": {"x": 1550, "y": 250},
                },
            ],
            "edges": [
                {
                    "id": "start_voice_text-source-intent_classify-target",
                    "source": "start_voice_text",
                    "target": "intent_classify",
                },
                {
                    "id": "intent_classify-source-route_by_intent-target",
                    "source": "intent_classify",
                    "target": "route_by_intent",
                },
                # route_by_intent branches
                {
                    "id": "route_by_intent-case_fixed-fixed_reply_local-target",
                    "source": "route_by_intent",
                    "sourceHandle": "case_fixed",
                    "target": "fixed_reply_local",
                },
                {
                    "id": "route_by_intent-case_local_action-local_action_parse-target",
                    "source": "route_by_intent",
                    "sourceHandle": "case_local_action",
                    "target": "local_action_parse",
                },
                {
                    "id": "route_by_intent-case_control-llm_control_action-target",
                    "source": "route_by_intent",
                    "sourceHandle": "case_control",
                    "target": "llm_control_action",
                },
                {
                    "id": "route_by_intent-case_ambiguous-tmpl_ambiguous_control-target",
                    "source": "route_by_intent",
                    "sourceHandle": "case_ambiguous",
                    "target": "tmpl_ambiguous_control",
                },
                {
                    "id": "route_by_intent-case_knowledge-knowledge_retrieve-target",
                    "source": "route_by_intent",
                    "sourceHandle": "case_knowledge",
                    "target": "knowledge_retrieve",
                },
                {
                    "id": "route_by_intent-false-tmpl_complex_fallback-target",
                    "source": "route_by_intent",
                    "sourceHandle": "false",
                    "target": "tmpl_complex_fallback",
                },
                # downstream of knowledge retrieval
                {
                    "id": "knowledge_retrieve-source-llm_robot_knowledge-target",
                    "source": "knowledge_retrieve",
                    "target": "llm_robot_knowledge",
                },
                # converge to aggregator
                {
                    "id": "fixed_reply_local-source-merge_outputs-target",
                    "source": "fixed_reply_local",
                    "target": "merge_outputs",
                },
                {
                    "id": "local_action_parse-source-merge_outputs-target",
                    "source": "local_action_parse",
                    "target": "merge_outputs",
                },
                {
                    "id": "llm_control_action-source-merge_outputs-target",
                    "source": "llm_control_action",
                    "target": "merge_outputs",
                },
                {
                    "id": "tmpl_ambiguous_control-source-merge_outputs-target",
                    "source": "tmpl_ambiguous_control",
                    "target": "merge_outputs",
                },
                {
                    "id": "llm_robot_knowledge-source-merge_outputs-target",
                    "source": "llm_robot_knowledge",
                    "target": "merge_outputs",
                },
                {
                    "id": "tmpl_complex_fallback-source-merge_outputs-target",
                    "source": "tmpl_complex_fallback",
                    "target": "merge_outputs",
                },
                # final nodes
                {
                    "id": "merge_outputs-source-code_convert-target",
                    "source": "merge_outputs",
                    "target": "code_convert",
                },
                {
                    "id": "code_convert-source-end_result-target",
                    "source": "code_convert",
                    "target": "end_result",
                },
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1}
        }
    }
}

output_path = Path(__file__).with_name("voice_ros2_dify_v06.yml")
with open(output_path, "w") as f:
    yaml.dump(dsl, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

print(f"✅ DSL v0.6.0 文件已生成: {output_path}")
print(f"   Workflow ID: {WF_ID}")
print(f"   流程: 开始 → 意图分类 → 意图路由 → 各自条件分支 → 合并输出 → JSON验证 → 输出")
print("\n📋 使用步骤:")
print("   1. Dify → 知识库 → 创建知识库，上传机械臂指令修正文档")
print("   2. Dify → 工作室 → 导入此 DSL 文件")
print("   3. 打开工作流 → 知识库检索节点 → 选择刚创建的知识库")
print("   4. 各LLM节点 → 选择 Ollama → qwen2")
print("   5. 发布工作流")
