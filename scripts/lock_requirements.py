#!/usr/bin/env python3
"""Create a hash-checked lock for one reviewed Python/platform wheelhouse."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename


def _artifact_key(path: Path) -> tuple[str, str]:
    if path.name.endswith(".whl"):
        name, version, _, _ = parse_wheel_filename(path.name)
    else:
        name, version = parse_sdist_filename(path.name)
    return canonicalize_name(name), str(version)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("resolved", type=Path)
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    artifacts: dict[tuple[str, str], list[Path]] = {}
    for path in args.wheelhouse.iterdir():
        if path.is_file():
            artifacts.setdefault(_artifact_key(path), []).append(path)

    locked: list[str] = []
    for raw_line in args.resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        if "==" not in line:
            raise ValueError(f"unlocked requirement: {line}")
        name, version = line.split("==", 1)
        matches = artifacts.get((canonicalize_name(name), version), [])
        if not matches:
            raise ValueError(f"missing artifact for {line}")
        hashes = sorted({_sha256(path) for path in matches})
        continuation = " \\" + "\n    "
        suffix = continuation.join(f"--hash=sha256:{value}" for value in hashes)
        locked.append(f"{line}{continuation}{suffix}")

    header = (
        "# Generated for CPython 3.10 / Linux x86_64 from voice-wake.in.\n"
        "# Regenerate only from a reviewed wheelhouse with lock_requirements.py.\n"
        "--require-hashes\n\n"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(header + "\n".join(locked) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
