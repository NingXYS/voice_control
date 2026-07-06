#!/usr/bin/env python3
"""生成 Dify Workflow DSL v0.6.0 YAML 文件（含知识库检索节点）"""
import uuid
import yaml

WF_ID = str(uuid.uuid4())
NODE_START = "start_voice_text"
NODE_KNOWLEDGE = "knowledge_retrieve"
NODE_LLM = "llm_extract"
NODE_CODE = "code_convert"
NODE_END = "end_result"

# System Prompt：知识库参考部分放在最前面，LLM 会优先遵循
SYSTEM_PROMPT = """你是双臂机械臂控制助手，负责将用户的自然语言指令转换为JSON。

【知识库参考 - 优先遵循】
以下是从知识库检索到的相关指令修正信息，请优先参考：
{{#knowledge_retrieve.result#}}

【指令类型判断 - 优先判断】
- 用户询问机器人信息/功能/介绍/闲聊 → 输出 reply 类型：{"reply": "回复内容"}
- 用户要求控制机械臂动作 → 输出 control 类型（带 action 字段）

【动作类型选择规则 - 严格遵循】
- 用户提到"关节""旋转""转动" → action: "move_joint"
- 用户提到"上下左右前后""移动""走""抬""降" → action: "move_cartesian"

【坐标系定义 - 严格遵循】
- 向右/右 → x: 正数
- 向左/左 → x: 负数
- 向前/前 → y: 正数
- 向后/后 → y: 负数
- 向上/上/升 → z: 正数
- 向下/下/降 → z: 负数

【关节编号】
- 第1-6关节对应 joint: 1-6

【单位换算 - 必须执行】
- 距离：厘米→米，如 10厘米=0.1米，5厘米=0.05米
- 角度：度→弧度，如 30度≈0.524弧度，45度≈0.785弧度

【默认值】
- 未指定距离：默认移动 0.05米（5厘米）
- 未指定角度：默认旋转 0.1弧度
- relative 始终为 true
- 未说"反转"/"反向"时，value 为正数

【输出约束 - 必须遵守】
- 只输出纯JSON，不包含任何其他文字、markdown标记、代码块
- 单条指令输出JSON对象，多条指令输出JSON数组，保持用户说话顺序
- 字段必须完整，顺序不影响解析

【验证清单 - 输出前逐项自检】
1. ✅ 指令类型对了吗？（闲聊→reply，控制→带action）
2. ✅ 单位已换算？（厘米→米，度→弧度）
3. ✅ 正负号正确？（左负右正，后负前正，下负上正）
4. ✅ 字段完整？（move_joint: action,arm,joint,value,type / move_cartesian: action,arm,x,y,z,relative）

【示例】
用户：你叫什么名字
输出：{"reply": "我是双臂机械臂助手，可以帮你控制机械臂抓取和移动物品"}

用户：你能做什么
输出：{"reply": "我可以控制左右两条机械臂，支持关节旋转和空间移动，比如'左臂向前10厘米'"}

用户：右臂向前5厘米
输出：{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true}

用户：左臂关节1旋转30度
输出：{"action":"move_joint","arm":"left","joint":1,"value":0.524,"type":"delta"}

用户：右臂回零位
输出：{"action":"home","arm":"right"}

用户：查询左臂状态
输出：{"action":"get_status","arm":"left"}

用户：你是什么机器人然后右臂向上5厘米
输出：[{"reply": "我是施耐力双臂六关节机械臂，拥有左右两条手臂，各六个关节"},{"action":"move_cartesian","arm":"right","x":0,"y":0,"z":0.05,"relative":true}]

用户：右臂向前5厘米左臂向上10厘米
输出：[{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true},{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.1,"relative":true}]

用户：左臂关节3反转30度
输出：{"action":"move_joint","arm":"left","joint":3,"value":-0.524,"type":"delta"}

用户：左臂向上右臂向前再左臂向右
输出：[{"action":"move_cartesian","arm":"left","x":0,"y":0,"z":0.05,"relative":true},{"action":"move_cartesian","arm":"right","x":0,"y":0.05,"z":0,"relative":true},{"action":"move_cartesian","arm":"left","x":0.05,"y":0,"z":0,"relative":true}]"""

CODE_NODE_CODE = """import json
import re

def main(raw_json: str) -> dict:
    result = raw_json.strip()
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
        "description": "将语音识别的自然语言指令解析为ROS2机械臂控制JSON命令（含知识库修正）",
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
                    "id": NODE_START,
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
                    "id": NODE_KNOWLEDGE,
                    "data": {
                        "type": "knowledge-retrieval",
                        "title": "① 知识库检索",
                        "description": "从知识库中检索与指令相关的修正信息",
                        "query_variable_selector": [NODE_START, "text"],
                        "dataset_ids": [],
                        "retrieval_mode": "multiple",
                        "top_k": 3,
                        "score_threshold": 0.5,
                    },
                    "position": {"x": 300, "y": 200},
                },
                {
                    "id": NODE_LLM,
                    "data": {
                        "type": "llm",
                        "title": "② 指令解析(结合知识库)",
                        "description": "结合知识库修正信息，将自然语言指令转换为JSON命令",
                        "context": {"enabled": False},
                        "model": {
                            "mode": "chat",
                            "provider": "",
                            "name": "",
                            "completion_params": {
                                "temperature": 0.1,
                                "max_tokens": 512,
                                "top_p": 0.95,
                                "stop": []
                            }
                        },
                        "prompt_template": [
                            {"role": "system", "text": SYSTEM_PROMPT},
                            {"role": "user", "text": "{{#start_voice_text.text#}}"}
                        ],
                        "variables": []
                    },
                    "position": {"x": 580, "y": 200},
                },
                {
                    "id": NODE_CODE,
                    "data": {
                        "type": "code",
                        "title": "③ JSON验证与清理",
                        "description": "验证LLM输出的JSON并确保格式正确",
                        "code_language": "python3",
                        "code": CODE_NODE_CODE,
                        "variables": [
                            {"variable": "raw_json", "value_selector": [NODE_LLM, "text"]}
                        ],
                        "outputs": {"result": {"type": "string"}}
                    },
                    "position": {"x": 860, "y": 200},
                },
                {
                    "id": NODE_END,
                    "data": {
                        "type": "end",
                        "title": "输出",
                        "outputs": [
                            {"variable": "result", "value_selector": [NODE_CODE, "result"]}
                        ]
                    },
                    "position": {"x": 1100, "y": 200},
                },
            ],
            "edges": [
                {"source": NODE_START, "target": NODE_KNOWLEDGE},
                {"source": NODE_KNOWLEDGE, "target": NODE_LLM},
                {"source": NODE_LLM, "target": NODE_CODE},
                {"source": NODE_CODE, "target": NODE_END},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1}
        }
    }
}

output_path = "/home/ning/model/lyz/src/voice_control/scripts/voice_ros2_dify_v06.yml"
with open(output_path, "w") as f:
    yaml.dump(dsl, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

print(f"✅ DSL v0.6.0 文件已生成: {output_path}")
print(f"   Workflow ID: {WF_ID}")
print(f"   流程: 开始 → ①知识库检索 → ②指令解析(结合知识库) → ③JSON验证 → 输出")
print("\n📋 使用步骤:")
print("   1. Dify → 知识库 → 创建知识库，上传机械臂指令修正文档")
print("   2. Dify → 工作室 → 导入此 DSL 文件")
print("   3. 打开工作流 → ①知识库检索节点 → 选择刚创建的知识库")
print("   4. ②指令解析节点 → 选择 Ollama → qwen2")
print("   5. 发布工作流")
