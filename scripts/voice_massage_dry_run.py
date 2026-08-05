#!/usr/bin/env python3
"""No-hardware worker used to exercise the massage voice workflow safely."""
from __future__ import annotations

import argparse
import time
from pathlib import Path


def write_header(path: Path, count: int) -> None:
    rows = []
    for index in range(count):
        # Harmless synthetic values; this worker never sends them to a robot.
        rows.append(
            "  {{%.6f, 0.000000, 0.500000, M_PI, 0.0, M_PI}}%s // P%d"
            % (0.400000 + index * 0.01, "," if index + 1 < count else " ", index)
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#pragma once\n\n#include <array>\n#include <cmath>\n\n"
        f"inline const std::array<std::array<double, 6>, {count}> "
        "capturedPostures = {{\n" + "\n".join(rows) + "\n}};\n",
        encoding="utf-8",
    )


def teach(output: Path) -> int:
    print("[DRY RUN] 模拟拖动示教已启动，不会连接机械臂。", flush=True)
    print("按回车生成一个假点位，输入 q 保存退出。", flush=True)
    count = 0
    for raw in iter(input, None):
        text = raw.strip()
        if text.lower() == "q":
            break
        if text:
            print("请输入空行记录，或输入 q 退出。", flush=True)
            continue
        print(f"[DRY RUN] 已记录 P{count}", flush=True)
        count += 1
    if count:
        write_header(output, count)
        print(f"[DRY RUN] 已保存 {count} 个假点位到 {output}", flush=True)
    else:
        print("[DRY RUN] 未记录点位，不生成文件。", flush=True)
    return 0


def massage(seconds: float) -> int:
    print("[DRY RUN] 模拟按摩开始，不会连接或驱动机械臂。", flush=True)
    time.sleep(max(0.0, seconds))
    print("[DRY RUN] 模拟按摩完成。", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    teaching = sub.add_parser("teaching")
    teaching.add_argument("output", type=Path)
    massage_parser = sub.add_parser("massage")
    massage_parser.add_argument("--seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.mode == "teaching":
        return teach(args.output)
    return massage(args.seconds)


if __name__ == "__main__":
    raise SystemExit(main())
