"""读取现有 Menxing 状态行；不启动或连接机器人。"""
from pathlib import Path
import math
import re
import stat
from force_control import MAX_FORCE


def parse_console_force(line):
    if not line.startswith(("[Menxing] ", "[Roudong] ")):
        return None
    fields = dict(re.findall(r"\b(elapsed_s|requested_N|target_N|feedback_N|phase)=([^\s]+)", line))
    try:
        elapsed, requested, target, feedback = (float(fields[key]) for key in
                                               ("elapsed_s", "requested_N", "target_N", "feedback_N"))
    except (KeyError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (elapsed, requested, target, feedback)):
        return None
    if elapsed < 0 or not 0 <= requested <= MAX_FORCE or not 0 <= target <= MAX_FORCE:
        return None
    # 校零阶段的 displayForce 尚未更新，不能把初始化的 0 冒充反馈读数。
    return {"requested_n": requested, "target_n": target,
            "measured_n": None if fields.get("phase") == "calibration" else feedback,
            "controller_time_s": elapsed}


class ConsoleForceTail:
    def __init__(self, path):
        self.path = Path(path)
        self._identity = None
        self._offset = 0
        self._partial = b""
        self._skip = False

    def reset(self):
        self._identity = None

    def read(self):
        try:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode):
                return []
            identity = (info.st_dev, info.st_ino)
            if identity != self._identity or info.st_size < self._offset:
                # 首次打开或换文件只跟随后续新增行，不将历史日志标记成实时数据。
                self._identity, self._offset, self._partial = identity, info.st_size, b""
                self._skip = False
                return []
            with self.path.open("rb") as stream:
                stream.seek(self._offset)
                chunk = stream.read(65536)
                self._offset = stream.tell()
        except OSError:
            return []
        values = []
        pieces = (self._partial + chunk).split(b"\n")
        self._partial = pieces.pop()
        for piece in pieces:
            if self._skip:
                self._skip = False
                continue
            if len(piece) > 4096:
                continue
            sample = parse_console_force(piece.decode("utf-8", errors="replace").rstrip("\r"))
            if sample is not None:
                values.append(sample)
        if len(self._partial) > 4096:
            self._partial, self._skip = b"", True
        return values[-1:]
