"""按摩目标力的确定性解析及单次请求客户端；不启动运动。"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import re
import socket
import unicodedata


MIN_FORCE = 2.0
MAX_FORCE = 70.0
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
NUMBER = r"(?:[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百]+(?:点[零〇一二两三四五六七八九]+)?)"


@dataclass(frozen=True)
class ForceCommand:
    operation: str
    value: float | None = None


def chinese_number(text: str) -> float:
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        return float(text)
    digits = {c: i for i, c in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    whole, dot, fraction = text.partition("点")
    if whole.count("十") > 1 or "百" in whole:
        raise ValueError("不支持的数字")
    if "十" in whole:
        if not re.fullmatch(r"(?:十[一二三四五六七八九]?|[二三四五六七八九]十[一二三四五六七八九]?)", whole):
            raise ValueError("不支持的数字")
        left, right = whole.split("十")
        value = (digits[left] if left else 1) * 10 + (digits[right] if right else 0)
    elif len(whole) == 1:
        value = digits[whole]
    else:
        raise ValueError("不支持的数字")
    if dot:
        value += float("0." + "".join(str(digits[c]) for c in fraction))
    return float(value)


def parse_force_command(text: str, step: float = 2.0) -> ForceCommand | None:
    if not isinstance(text, str) or len(text) > 80:
        return None
    if isinstance(step, bool) or not isinstance(step, (int, float)) or not math.isfinite(step) or not 0 < step <= MAX_FORCE - MIN_FORCE:
        return None
    # 只匹配完整口语模板；不做子串检索、数字纠错或删除句内否定词。
    value = unicodedata.normalize("NFKC", text).lower().strip()
    if re.search(r"[0-9]\s+[0-9]", value):
        return None
    value = re.sub(r"[。.!！?？]+$", "", value)
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"^(?:请你?|麻烦你?|劳驾),?", "", value)
    value = re.sub(r"(?:吧|呀|啊)?(?:,?谢谢你?)?$", "", value)
    value = re.sub(r"(?:就行了?|就好了?|就可以了)$", "", value)
    beneficiary = r"(?:(?:给我|帮我|替我),?)?"
    subject = r"(?:把|将)?(?:按摩的?)?(?:力度|力道|力量|目标力|力值|力),?"
    # 礼貌词只出现在指令前后；主语和受益词的位置受限，不能拼接两条指令。
    body = re.fullmatch(rf"{beneficiary}(?:{subject})?{beneficiary}(.+)", value)
    if not body:
        return None
    content = body[1]
    has_subject = re.fullmatch(rf"{beneficiary}{subject}{beneficiary}.+", value) is not None
    if value in {"当前力度", "当前力大小", "现在力度多少", "现在多大力", "力度多少", "查询力度", "查询力大小", "查询目标力", "目标力多少", "当前目标力", "当前力量", "现在力量多少", "力量多少", "查询力量"}:
        return ForceCommand("status")
    if re.fullmatch(rf"{beneficiary}(?:查询|查一下|看看|看一下)(?:当前|现在)?(?:的)?(?:按摩)?(?:力度|力道|力量|目标力|力)", value):
        return ForceCommand("status")
    if has_subject and content in {"多少", "多大", "是多少", "是多大", "现在多少", "现在是多少"}:
        return ForceCommand("status")

    unit = r"(?:个?牛顿|牛|n)(?:的力(?:度)?)?"
    absolute = r"(?:(?:设置|设定|设|调整|调节|调|改)(?:成|为|到|至)|(?:调)?[轻重大小高低](?:到|至)|(?:增加|减少|加大|减小|加重|减轻|提高|降低|加|减|升|降)(?:到|至)|到|至|为)"
    match = re.fullmatch(rf"({absolute})?({NUMBER}){unit}", content)
    if match and (has_subject or match[1]):
        try:
            return ForceCommand("force", chinese_number(match[2]))
        except (ValueError, KeyError):
            return None

    up = r"(?:加大|加重|增大|增加|增强|提高|上调|调高|加上|加|增|升|大|重|强|多|调大|调重|调整大|调整重|调节大|调节重|往(?:大|重|上)(?:调|加))"
    down = r"(?:减小|减轻|减少|减弱|降低|下调|调低|减去|减|降|小|轻|弱|少|调小|调轻|调整小|调整轻|调节小|调节轻|往(?:小|轻|下)(?:调|减))"
    modifier = r"(?:再)?(?:稍微|稍稍)?"
    match = re.fullmatch(rf"{modifier}({up}|{down})({NUMBER}){unit}", content)
    if match:
        try:
            amount = chinese_number(match[2])
        except (ValueError, KeyError):
            return None
        if not 0 < amount <= MAX_FORCE - MIN_FORCE:
            return None
        return ForceCommand("adjust", -amount if re.fullmatch(down, match[1]) else amount)

    small_step = r"(?:一点点|一点儿|一点|点儿|一些|点|些)"
    for direction, sign in ((up, 1), (down, -1)):
        matched = re.fullmatch(rf"{modifier}({direction}){small_step}(力|力度)?", content)
        if matched:
            # 高低、升降也可能指位置，必须有力度主语或明确的力词。
            spatial = r"(?:升|降|提高|降低|上调|下调|调高|调低|往上(?:调|加)|往下(?:调|减))"
            if not has_subject and not matched[2] and re.fullmatch(spatial, matched[1]):
                return None
            if content == "重点" and not has_subject:
                return None
            return ForceCommand("adjust", sign * step)
    if re.fullmatch(rf"{modifier}(?:加点力度|加点力|加大力度|增加力度|加大|加重|多用点力|用力一点|用力点)", content):
        return ForceCommand("adjust", step)
    if re.fullmatch(rf"{modifier}(?:减点力度|减点力|减小力度|减轻力度|减小|减轻|少用点力|放轻一点|放轻点)", content):
        return ForceCommand("adjust", -step)
    return None


class BridgeError(RuntimeError):
    pass


class ForceClient:
    def __init__(self, host: str, port: int, token: str, timeout: float = 1.0):
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("VOICE_FORCE_TOKEN 需要 32～128 位字母、数字、下划线或短横线")
        if not 1 <= port <= 65535 or not math.isfinite(timeout) or not 0.05 <= timeout <= 5:
            raise ValueError("力控端口或超时配置无效")
        if not host or host.strip() != host:
            raise ValueError("力控主机配置无效")
        self.host, self.port, self.token, self.timeout = host, port, token, timeout

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("VOICE_FORCE_HOST", "127.0.0.1"),
                   int(os.environ.get("VOICE_FORCE_PORT", "19071")),
                   os.environ.get("VOICE_FORCE_TOKEN", ""),
                   float(os.environ.get("VOICE_FORCE_TIMEOUT", "1")))

    def request(self, command: ForceCommand) -> dict:
        if command.operation not in {"status", "force", "adjust"}:
            raise ValueError("仅允许目标力指令")
        suffix = ""
        if command.operation != "status":
            number = command.value
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise ValueError("目标力必须是有限数字")
            if command.operation == "force" and not MIN_FORCE <= number <= MAX_FORCE:
                raise ValueError("目标力范围为 2～70 牛顿")
            if command.operation == "adjust" and not 0 < abs(number) <= MAX_FORCE - MIN_FORCE:
                raise ValueError("增减幅度无效")
            suffix = f" {number:.12g}"
        wire = f"{self.token} {command.operation}{suffix}\n".encode("ascii")
        try:
            # 每次只发一次；超时后不重试，以免重复执行相对增减。
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
                connection.settimeout(self.timeout)
                connection.sendall(wire)
                data = bytearray()
                while b"\n" not in data and len(data) <= 2048:
                    chunk = connection.recv(512)
                    if not chunk:
                        break
                    data.extend(chunk)
            if len(data) > 2048 or not data.endswith(b"\n") or data.count(b"\n") != 1:
                raise ValueError("响应不完整")
            result = json.loads(data)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise BridgeError("控制端拒绝请求，未确认力度变更。")
            for field in ("requested_n", "target_n"):
                number = result.get(field)
                if isinstance(number, bool) or not isinstance(number, (float, int)) or not math.isfinite(number):
                    raise ValueError("响应字段无效")
            if not 0 <= result["requested_n"] <= MAX_FORCE or not 0 <= result["target_n"] <= MAX_FORCE:
                raise ValueError("响应越界")
            measured = result.get("measured_n")
            if measured is not None and (isinstance(measured, bool) or not isinstance(measured, (int, float)) or not math.isfinite(measured)):
                raise ValueError("实测力响应无效")
            valid = result.get("sample_valid")
            if valid is not None and (not isinstance(valid, bool) or (not valid and measured is not None)):
                raise ValueError("反馈有效性标记无效")
            for field in ("min_target_n", "max_target_n", "slew_rate_n_s", "sample_age_ms"):
                number = result.get(field)
                if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0):
                    raise ValueError("控制器参数响应无效")
            if result.get("source") not in {"manual", "curve"}:
                raise ValueError("会话状态无效")
            return result
        except BridgeError:
            raise
        except (OSError, ValueError, UnicodeError) as exc:
            raise BridgeError("未收到控制端确认，力度是否变更尚未确认，请先查询当前力度。") from exc


class ForceController:
    def __init__(self, client: ForceClient, step: float = 2.0):
        if not math.isfinite(step) or not 0 < step <= MAX_FORCE - MIN_FORCE:
            raise ValueError("VOICE_FORCE_STEP_N 必须大于 0 且不超过 68")
        self.client, self.step = client, step

    def handle_text(self, text: str, speaker=None):
        command = parse_force_command(text, self.step)
        result = None
        action = "force_rejected"
        if command is None:
            reply = "没听清力度，请再说一次。"
        else:
            try:
                result = self.client.request(command)
                if command.operation == "status":
                    if result.get("measured_n") is not None:
                        reply = f"当前反馈力{result['measured_n']:g}牛顿，请求目标力{result['requested_n']:g}牛顿。"
                    else:
                        reply = f"请求目标力{result['requested_n']:g}牛顿，反馈力暂未就绪。"
                    action = "force_status"
                else:
                    reply = f"已请求目标力{result['requested_n']:g}牛顿。"
                    if result.get("slew_rate_n_s", 0) > 0:
                        reply = f"已请求目标力{result['requested_n']:g}牛顿，按每秒{result['slew_rate_n_s']:g}牛顿平滑调整。"
                    action = "force_accepted"
            except (ValueError, BridgeError) as exc:
                reply = str(exc)
        if speaker is not None:
            speaker(reply)
        return [{"action": action, "reply": reply, "force": result,
                 "parsed": command is not None, "input_text": text}]
