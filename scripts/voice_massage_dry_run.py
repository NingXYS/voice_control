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


def teach(output: Path, required_points: int = 5) -> int:
    print("[DRY RUN] 模拟拖动示教已启动，不会连接机械臂。", flush=True)
    print(
        f"按回车生成一个假点位；录满 {required_points} 个点自动保存退出，也可输入 q 提前结束。",
        flush=True,
    )
    count = 0
    for raw in iter(input, None):
        text = raw.strip()
        if text.lower() == "q" or set(text.lower()) == {"q"}:
            break
        if text:
            print("请输入空行记录，或输入 q 退出。", flush=True)
            continue
        print(f"[DRY RUN] 已记录 P{count}", flush=True)
        count += 1
        if count >= required_points:
            print(f"[DRY RUN] 已录满 {required_points} 个点，自动结束。", flush=True)
            break
    if count:
        write_header(output, count)
        print(f"[DRY RUN] 已保存 {count} 个假点位到 {output}", flush=True)
    else:
        print("[DRY RUN] 未记录点位，不生成文件。", flush=True)
    return 0


def massage(seconds: float, level: int, parts: list[str]) -> int:
    selected = "全部位置" if parts == ["all"] else "、".join(parts)
    print(
        f"[DRY RUN] 模拟按摩开始：位置={selected}，力度={level}级；不会连接或驱动机械臂。",
        flush=True,
    )
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
    massage_parser.add_argument("--level", type=int, choices=range(1, 6), required=True)
    massage_parser.add_argument(
        "--part",
        action="append",
        dest="parts",
        choices=(
            "left-shoulder", "right-shoulder", "back",
            "left-waist", "right-waist", "all",
        ),
        required=True,
    )
    args = parser.parse_args()
    if args.mode == "teaching":
        return teach(args.output)
    return massage(args.seconds, args.level, args.parts)


if __name__ == "__main__":
    raise SystemExit(main())
