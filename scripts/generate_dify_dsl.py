#!/usr/bin/env python3
"""生成 Dify Workflow DSL v2 YAML 文件"""
import uuid
import yaml
import json

# ==================== 生成 UUID ====================
WF_ID = str(uuid.uuid4())
NODE_START = "b30b7ecd-868a-4421-b48d-7e7ca0978e32"
NODE_LLM = "a016d867-e9e3-4009-b80c-6c2bfc9192a2"
NODE_CODE = "0bfcc33e-db77-40b9-9a43-1292d2ed1c1d"
NODE_END = "c6e199f9-8cb4-4b81-a0a9-c1e694a7f77a"
EDGE_1 = "54ded71b-2fbf-4598-bd34-18e5b931dd94"
EDGE_2 = "b952119b-5ac9-4ff6-9111-9d4db58a2d4b"
EDGE_3 = "407fed31-66e0-4655-b979-b2c20b796b9e"
PROMPT_SYS = "cb95bbcd-1394-4807-819c-958dd04969c3"
PROMPT_USER = "58a02c5a-bea5-42df-87f7-937473245218"

# ==================== 优化后的 SYSTEM PROMPT ====================
SYSTEM_PROMPT = """你是一个双臂机械臂控制助手。请从用户指令中提取结构化信息。

【思考流程】
1. 先理解用户说了几个动作，按顺序编号
2. 对每个动作判断：是移动(move_cartesian)还是关节旋转(move_joint)
3. 确定是哪条臂(left/right)
4. 提取数值并换算单位
5. 确定正负号（左负右正，后负前正，下负上正）

【动作判断规则】
- 移动类关键词：上下左右前后、移动、走、抬、降
- 关节类关键词：关节、旋转、转动

【坐标系】
- 右→x正  左→x负  前→y正  后→y负  上(升)→z正  下(降)→z负

【单位换算】
- 距离：厘米÷100→米（如5厘米=0.05米）
- 角度：度×π/180→弧度（如30度≈0.524弧度）

【输出格式 - 严格按照以下模板】
每行一个动作，格式：
动作N | 臂: left/right | 类型: 移动/旋转 | 方向: 上下左右前后或关节编号 | 数值: 数字或"无" | 单位: 厘米/度/无 | 正负: 正/负

注意：
- 如果用户没说臂，用"未指定"
- 如果没说数值，数值写"无"
- 只说"反转""反向"则正负为"负"
- 不要输出JSON，只输出结构化文本"""

CODE_NODE_CODE = """import json
import re
import math

def main(extracted: str) -> dict:
    lines = [l.strip() for l in extracted.strip().split('\\n') if l.strip()]
    commands = []
    dir_map = {'右': ('x', 1), '左': ('x', -1),
               '前': ('y', 1), '后': ('y', -1),
               '上': ('z', 1), '下': ('z', -1)}
    
    for line in lines:
        parts = [p.strip() for p in line.split('|')]
        item = {}
        for p in parts:
            if ':' in p:
                key, val = p.split(':', 1)
                item[key.strip()] = val.strip()
        
        arm = item.get('臂', '未指定')
        arm = 'right' if arm == '未指定' else arm
        move_type = item.get('类型', '移动')
        direction = item.get('方向', '')
        val_str = item.get('数值', '无')
        unit = item.get('单位', '无')
        sign = item.get('正负', '正')
        
        # 数值处理
        if val_str == '无':
            value = 0.05 if move_type == '移动' else 0.1
        else:
            value = float(val_str)
            if unit == '厘米':
                value = value / 100.0
            elif unit == '度':
                value = value * math.pi / 180.0
        
        if sign == '负':
            value = -value
        
        if move_type == '旋转' or '关节' in direction:
            joint_match = re.search(r'(\\d+)', direction)
            joint = int(joint_match.group(1)) if joint_match else 1
            commands.append({
                "action": "move_joint",
                "arm": arm,
                "joint": joint,
                "value": round(value, 4),
                "type": "delta"
            })
        else:
            x, y, z = 0.0, 0.0, 0.0
            for ch in direction:
                if ch in dir_map:
                    axis, sgn = dir_map[ch]
                    if axis == 'x': x = sgn * abs(value)
                    elif axis == 'y': y = sgn * abs(value)
                    elif axis == 'z': z = sgn * abs(value)
            commands.append({
                "action": "move_cartesian",
                "arm": arm,
                "x": round(x, 4),
                "y": round(y, 4),
                "z": round(z, 4),
                "relative": True
            })
    
    return {"result": json.dumps(commands, ensure_ascii=False)}"""

# ==================== 构建 DSL ====================
dsl = {
    "app": {
        "description": "将语音识别的自然语言指令解析为ROS2机械臂控制JSON命令",
        "icon": "🤖",
        "icon_background": "#FFEAD5",
        "mode": "workflow",
        "name": "语音指令→ROS2命令",
    },
    "version": "2",
    "workflow": {
        "conversation_variables": [],
        "environment_variables": [],
        "features": {
            "file_upload": {
                "image": {"enabled": False},
                "enabled": False,
            },
        },
        "graph": {
            "edges": [
                {
                    "data": {"isInLoop": False, "sourceType": "node", "targetType": "node"},
                    "id": EDGE_1,
                    "source": NODE_START,
                    "sourceHandle": "source",
                    "target": NODE_LLM,
                    "targetHandle": "target",
                    "type": "custom",
                    "zIndex": 0,
                },
                {
                    "data": {"isInLoop": False, "sourceType": "node", "targetType": "node"},
                    "id": EDGE_2,
                    "source": NODE_LLM,
                    "sourceHandle": "source",
                    "target": NODE_CODE,
                    "targetHandle": "target",
                    "type": "custom",
                    "zIndex": 0,
                },
                {
                    "data": {"isInLoop": False, "sourceType": "node", "targetType": "node"},
                    "id": EDGE_3,
                    "source": NODE_CODE,
                    "sourceHandle": "source",
                    "target": NODE_END,
                    "targetHandle": "target",
                    "type": "custom",
                    "zIndex": 0,
                },
            ],
            "nodes": [
                {
                    "data": {
                        "desc": "",
                        "selected": False,
                        "title": "开始",
                        "type": "start",
                        "variables": [
                            {
                                "default": "",
                                "label": "语音文本",
                                "max_length": 512,
                                "required": True,
                                "type": "text-input",
                                "variable": "text",
                            }
                        ],
                    },
                    "height": 98,
                    "id": NODE_START,
                    "position": {"x": 80, "y": 200},
                    "positionAbsolute": {"x": 80, "y": 200},
                    "type": "start",
                    "width": 200,
                },
                {
                    "data": {
                        "answer": "",
                        "desc": "将自然语言指令提取为结构化信息",
                        "selected": False,
                        "title": "① 指令信息提取",
                        "type": "llm",
                        "variables": [],
                        "context": {"enabled": False},
                        "model": {
                            "completion_params": {
                                "stop": [],
                                "temperature": 0.1,
                                "max_tokens": 512,
                                "top_p": 0.95,
                            },
                            "mode": "chat",
                            "name": "",
                            "provider": "",
                        },
                        "prompt_template": [
                            {
                                "id": PROMPT_SYS,
                                "role": "system",
                                "text": SYSTEM_PROMPT,
                            },
                            {
                                "id": PROMPT_USER,
                                "role": "user",
                                "text": "{{#start.text#}}",
                            },
                        ],
                    },
                    "height": 260,
                    "id": NODE_LLM,
                    "position": {"x": 380, "y": 200},
                    "positionAbsolute": {"x": 380, "y": 200},
                    "type": "llm",
                    "width": 240,
                },
                {
                    "data": {
                        "code": CODE_NODE_CODE,
                        "code_language": "python",
                        "desc": "将结构化信息转换为JSON命令（单位换算、坐标映射）",
                        "outputs": [
                            {"type": "string", "variable": "result"},
                        ],
                        "selected": False,
                        "title": "② 参数计算与JSON组装",
                        "type": "code",
                        "variables": [
                            {
                                "variable": "extracted",
                                "value_selector": [NODE_LLM, "text"],
                            }
                        ],
                    },
                    "height": 220,
                    "id": NODE_CODE,
                    "position": {"x": 720, "y": 200},
                    "positionAbsolute": {"x": 720, "y": 200},
                    "type": "code",
                    "width": 240,
                },
                {
                    "data": {
                        "desc": "",
                        "selected": False,
                        "title": "输出",
                        "type": "end",
                        "outputs": [
                            {
                                "variable": "result",
                                "value_selector": [NODE_CODE, "result"],
                            }
                        ],
                    },
                    "height": 98,
                    "id": NODE_END,
                    "position": {"x": 1060, "y": 200},
                    "positionAbsolute": {"x": 1060, "y": 200},
                    "type": "end",
                    "width": 200,
                },
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
        "id": WF_ID,
        "title": "语音指令解析工作流",
    },
}

# ==================== 写入文件 ====================
output_path = "/home/ning/model/lyz/src/voice_control/scripts/voice_ros2_dify.yml"
with open(output_path, "w") as f:
    yaml.dump(dsl, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)

print(f"✅ DSL 文件已生成: {output_path}")
print(f"   Workflow ID: {WF_ID}")
print(f"   节点数: 4 (开始 → LLM → Code → 结束)")
print("\n请打开 Dify Web UI (http://localhost:80)")
print("点击右上角头像 → 设置 → 数据源 → 导入 DSL 文件")
print(f"选择 {output_path} 即可导入工作流")
