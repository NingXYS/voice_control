#!/usr/bin/env python3
"""Validate that a wake phrase can be represented by a KWS tokens file."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tokens")
    parser.add_argument("--phrase", default="小西小西")
    args = parser.parse_args()

    tokens_path = Path(args.tokens)
    if not tokens_path.is_file():
        raise SystemExit(f"tokens file not found: {tokens_path}")

    try:
        lines = tokens_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"unable to read tokens file: {tokens_path}: {exc}") from exc

    tokens = set()
    for line in lines:
        if line.strip():
            tokens.add(line.split()[0])
    units = list(args.phrase.replace(" ", ""))
    missing = [unit for unit in units if unit not in tokens]
    if missing:
        raise SystemExit("tokens missing: " + " ".join(sorted(set(missing))))
    print(" ".join(units))


if __name__ == "__main__":
    main()
